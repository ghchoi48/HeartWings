"""인증된 루프백 llama-server의 비동기 실행 수명 관리."""
import asyncio
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys

import httpx

from maeumnarae.core.paths import PROJECT_ROOT, RESOURCE_ROOT
from .models import catalog, supports_reasoning
from .reasoning import ThinkStreamSplitter
from .types import AIError, GenerationEvent


def platform_key():
    machine = platform.machine().lower()
    if sys.platform == 'darwin' and machine in {'arm64', 'aarch64'}:
        return 'macos-arm64'
    if sys.platform == 'win32' and machine in {'amd64', 'x86_64'}:
        return 'windows-x64'
    return None


def engine_path():
    key = platform_key()
    if not key:
        return None
    return RESOURCE_ROOT / 'ai/runtime' / key / ('llama-server.exe' if sys.platform == 'win32' else 'llama-server')


def request_payload(record, request):
    profile = next((item for item in catalog(include_unrecommended=True) if item.profile == record.profile), None)
    # 추천 목록에서 제외된 기존 EXAONE 3.5 설치도 같은 실행 설정을 유지한다.
    system_prompt = (profile.system_prompt if profile else
                     'You are EXAONE model from LG AI Research, a helpful assistant.'
                     if record.profile == 'exaone' else 'You are a helpful assistant. Respond in Korean.')
    if request.system_instruction:
        system_prompt += '\n' + request.system_instruction
    reasoning = request.reasoning_enabled and supports_reasoning(record)
    payload = {
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': request.prompt},
        ],
        'stream': True, 'max_tokens': max(request.max_tokens, 2048) if reasoning else request.max_tokens,
        'temperature': request.temperature,
        'cache_prompt': False, 'reasoning_format': 'deepseek',
    }
    if profile and profile.template_kwargs:
        payload['chat_template_kwargs'] = dict(profile.template_kwargs)
        if 'enable_thinking' in payload['chat_template_kwargs']:
            payload['chat_template_kwargs']['enable_thinking'] = reasoning
    if request.output_schema is not None:
        payload['response_format'] = {'type': 'json_object', 'schema': request.output_schema}
    return payload


class LlamaServerRuntime:
    def __init__(self):
        self.process = None
        self.client = None
        self.model_id = None
        self.backend = ''

    @property
    def supported(self):
        return platform_key() is not None

    async def stop(self):
        client, process = self.client, self.process
        self.client = self.process = self.model_id = None
        # 정리 코루틴이 다시 취소되어도 감시 프로세스가 EOF를 받아 종료하도록 먼저 닫는다.
        if process and process.stdin:
            process.stdin.close()
        if client:
            await client.aclose()
        if process:
            try:
                await asyncio.wait_for(process.wait(), 8)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()

    async def ensure_loaded(self, record):
        if self.model_id == record.id and self.process and self.process.returncode is None:
            return
        await self.stop()
        executable = engine_path()
        if executable is None:
            raise AIError('로컬 AI는 Windows x64와 Apple Silicon Mac에서 지원합니다.')
        if not executable.is_file():
            raise AIError('AI 엔진이 없습니다. 빌드 안내에 따라 엔진을 준비하거나 앱을 다시 설치해 주세요.')
        if not Path(record.path).is_file() or Path(record.path).stat().st_size != record.size:
            raise AIError('모델 파일이 이동되었거나 크기가 변경되었습니다. 다시 등록해 주세요.')
        for gpu in ([True, False] if sys.platform == 'darwin' else [False]):
            try:
                await self._start(executable, record, gpu)
                return
            except AIError:
                await self.stop()
                if not gpu:
                    raise
            except BaseException:
                await self.stop()
                raise

    async def _start(self, executable, record, gpu):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        key = secrets.token_urlsafe(32)
        alias = 'heartwings-' + secrets.token_hex(12)
        args = [str(executable), '--model', record.path, '--host', '127.0.0.1', '--port', str(port),
                '--ctx-size', '4096', '--parallel', '1', '--n-gpu-layers', '99' if gpu else '0',
                '--jinja', '--no-webui', '--no-warmup', '--log-disable', '--alias', alias]
        profile = next((item for item in catalog(include_unrecommended=True) if item.profile == record.profile), None)
        if profile and profile.chat_template_file:
            template_root = (RESOURCE_ROOT / 'ai').resolve()
            template = (template_root / profile.chat_template_file).resolve()
            if not template.is_relative_to(template_root) or not template.is_file():
                raise AIError('모델의 채팅 템플릿을 찾을 수 없습니다. 앱 설치 상태를 확인해 주세요.')
            args += ['--chat-template-file', str(template)]
        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--ai-engine-guard', *args]
        else:
            command = [sys.executable, str(PROJECT_ROOT / 'main.py'), '--ai-engine-guard', *args]
        environment = dict(os.environ)
        # PyInstaller 자식 실행을 별도 앱 인스턴스로 초기화한다.
        if getattr(sys, 'frozen', False):
            environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.process.stdin.write((key + '\n').encode('ascii'))
            await self.process.stdin.drain()
            self.client = httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                                           headers={'Authorization': f'Bearer {key}'}, timeout=60)
            async with asyncio.timeout(180):
                while self.process.returncode is None:
                    try:
                        response = await self.client.get('/health', timeout=2)
                        if response.status_code == 200:
                            identity = await self.client.get('/v1/models', timeout=2)
                            if identity.status_code != 200 or not any(
                                    model.get('id') == alias for model in identity.json().get('data', [])):
                                raise AIError('AI 엔진 포트가 충돌했습니다. 다시 시도해 주세요.')
                            self.model_id = record.id
                            self.backend = 'Metal' if gpu else 'CPU'
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(.25)
        except (OSError, TimeoutError, ValueError, TypeError, AttributeError):
            pass
        raise AIError('모델을 로드하지 못했습니다. 모델 호환성·메모리·엔진 설치 상태를 확인해 주세요.')

    async def check_context(self, record, request):
        """동일한 모델/채팅 설정으로 렌더링한 입력을 실제 토크나이저로 센다."""
        if self.client is None:
            raise AIError('AI 엔진이 준비되지 않았습니다.')
        try:
            async with asyncio.timeout(30):
                payload = request_payload(record, request)
                response = await self.client.post('/apply-template', json=payload)
                response.raise_for_status()
                prompt = response.json()['prompt']
                if not isinstance(prompt, str):
                    raise ValueError()
                response = await self.client.post('/tokenize', json={
                    'content': prompt, 'add_special': True, 'parse_special': True})
                response.raise_for_status()
                tokens = response.json()['tokens']
                if not isinstance(tokens, list):
                    raise ValueError()
                if len(tokens) + request.max_tokens + 32 > 4096:
                    raise AIError('입력과 출력 예산이 모델 컨텍스트를 초과합니다. 메모나 양식 지침을 줄여 주세요.')
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            raise AIError('엔진의 입력 길이 검사를 지원하지 않거나 검사에 실패했습니다. 엔진 버전을 확인하세요.') from None

    async def generate(self, record, request):
        if self.client is None:
            raise AIError('AI 엔진이 준비되지 않았습니다.')
        splitter = ThinkStreamSplitter()
        finished = False
        try:
            async with asyncio.timeout(180):
                async with self.client.stream('POST', '/v1/chat/completions',
                                              json=request_payload(record, request)) as response:
                    if request.output_schema is not None and response.status_code in (400, 422, 501):
                        raise AIError('구조화 출력 요청을 처리하지 못했습니다. 엔진과 모델 호환성을 확인하세요.')
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        if line[6:].strip() == '[DONE]':
                            if request.output_schema is not None and not finished:
                                raise AIError('구조화 출력이 정상 종료되지 않았습니다. 다시 시도해 주세요.')
                            for event in splitter.feed('', final=True):
                                yield event
                            yield GenerationEvent('done')
                            return
                        data = json.loads(line[6:])
                        if 'error' in data:
                            raise AIError('생성에 실패했습니다. 입력 길이와 모델을 확인해 주세요.')
                        choices = data.get('choices', [])
                        if choices:
                            finish = choices[0].get('finish_reason')
                            if request.output_schema is not None and finish not in (None, 'stop'):
                                raise AIError('출력이 제한에 도달하거나 중단되었습니다. 양식을 줄여 다시 시도하세요.')
                            finished = finished or finish == 'stop'
                            delta = choices[0].get('delta', {})
                            reasoning = delta.get('reasoning_content', '')
                            if reasoning and not isinstance(reasoning, str):
                                raise AIError('AI 추론 응답 형식이 올바르지 않습니다.')
                            if reasoning:
                                yield GenerationEvent('reasoning', reasoning)
                            token = delta.get('content', '')
                            if token and not isinstance(token, str):
                                raise AIError('AI 응답 형식이 올바르지 않습니다.')
                            if token:
                                if request.reasoning_enabled:
                                    for event in splitter.feed(token):
                                        yield event
                                else:
                                    yield GenerationEvent('text', token)
            raise AIError('AI 응답이 중간에 종료되었습니다. 다시 시도해 주세요.')
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise AIError('AI 응답 오류 또는 시간 초과입니다. 입력을 줄이거나 모델 상태를 확인해 주세요.') from None
