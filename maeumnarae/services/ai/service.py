"""모든 AI 진입점의 설정·세션·취소를 통제하는 앱 단위 서비스."""
import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
import time

from maeumnarae.core.settings_store import SettingsStore
from .models import ModelManager, catalog, supports_reasoning
from .runtime import LlamaServerRuntime
from .harness.store import HarnessStore, parse_definition
from .harness.runner import run as run_harness_workflow
from .types import AIError, AISettings, AIStatus, GenerationRequest


class AIService:
    def __init__(self, directory: Path, runtime=None):
        self.store = SettingsStore(directory / 'ai-settings.json')
        self.models = ModelManager(directory)
        self.harnesses = HarnessStore(directory)
        self.runtime = runtime or LlamaServerRuntime()
        self.settings = AISettings()
        self.error = self.models.error
        try:
            data = self.store.read()
            enabled, selected = data.get('enabled', False), data.get('selected_model_id')
            reasoning = data.get('reasoning_enabled', False)
            if (type(enabled) is not bool or type(reasoning) is not bool
                    or (selected is not None and not isinstance(selected, str))):
                raise ValueError()
            self.settings = AISettings(enabled, selected if selected in self.models.records else None, reasoning)
        except (OSError, ValueError, TypeError):
            self.error = 'AI 설정을 읽지 못했습니다. ai-settings.json을 확인해 주세요. AI는 꺼져 있습니다.'
        self.sessions: dict[str, Callable[[], bool]] = {}
        self.listeners = set()
        self.generation = None
        self.owner = None
        self.download_task = None
        self.download_id = None
        self.downloaded = self.total = 0
        self.loading = False
        self.revision = 0
        self._mutation = asyncio.Lock()
        self._last_progress = 0.0

    @property
    def status(self):
        state = ('미지원 환경' if not self.runtime.supported else '꺼짐' if not self.settings.enabled
                 else '모델 로딩 중' if self.loading else '생성 중' if self.generation
                 else '모델 준비 필요' if not self.settings.selected_model_id else '사용 가능')
        return AIStatus(state, self.error, self.download_id, self.downloaded, self.total)

    def subscribe(self, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def notify(self):
        for callback in tuple(self.listeners):
            try:
                callback()
            except Exception:
                # 삭제된 UI 클라이언트 때문에 서비스 작업을 실패시키지 않는다.
                self.listeners.discard(callback)

    def attach(self, session_id, is_unlocked):
        self.sessions[session_id] = is_unlocked

    def authorize(self, session_id):
        check = self.sessions.get(session_id)
        if check is None or not check():
            raise AIError('DB 잠금을 해제한 뒤 AI 설정을 사용해 주세요.')

    def _save(self, settings):
        try:
            self.store.update(lambda data: data.update(asdict(settings)))
        except (OSError, ValueError, TypeError):
            raise AIError('AI 설정을 저장하지 못했습니다. 설정 파일과 폴더 권한을 확인해 주세요.') from None
        self.settings = settings

    async def _cancel_generation(self):
        self.revision += 1
        task = self.generation
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.runtime.stop()

    async def cancel_download(self, session_id=None):
        if session_id is not None:
            self.authorize(session_id)
        task = self.download_task
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def set_enabled(self, session_id, enabled):
        async with self._mutation:
            self.authorize(session_id)
            if enabled and not self.runtime.supported:
                raise AIError('현재 환경은 로컬 AI를 지원하지 않습니다.')
            if not enabled:
                # 저장 실패 시에도 메모리에서는 즉시 차단한다.
                self.settings = replace(self.settings, enabled=False)
                await self._cancel_generation()
                await self.cancel_download()
            try:
                self._save(replace(self.settings, enabled=bool(enabled)))
                self.error = ''
            finally:
                self.notify()

    async def set_reasoning(self, session_id, enabled):
        async with self._mutation:
            self.authorize(session_id)
            if type(enabled) is not bool:
                raise AIError('추론 모드 설정이 올바르지 않습니다.')
            record = self.models.records.get(self.settings.selected_model_id)
            if enabled and not supports_reasoning(record):
                raise AIError('선택한 모델은 추론 모드 전환을 지원하지 않습니다.')
            try:
                self._save(replace(self.settings, reasoning_enabled=enabled))
                self.error = ''
            finally:
                self.notify()

    async def select_model(self, session_id, model_id):
        async with self._mutation:
            self.authorize(session_id)
            if model_id is not None and model_id not in self.models.records:
                raise AIError('등록된 모델을 선택해 주세요.')
            await self._cancel_generation()
            self.authorize(session_id)
            self._save(replace(self.settings, selected_model_id=model_id))
            self.error = ''
            self.notify()

    async def remove_model(self, session_id, model_id):
        async with self._mutation:
            self.authorize(session_id)
            await self._cancel_generation()
            self.authorize(session_id)
            if self.settings.selected_model_id == model_id:
                self._save(replace(self.settings, selected_model_id=None))
            try:
                self.models.remove(model_id)
            finally:
                self.notify()

    async def register_model(self, session_id, path):
        async with self._mutation:
            self.authorize(session_id)
            # 파일 검사는 워커에서, 등록과 설정 저장은 이벤트 루프에서 직렬화한다.
            from .gguf import inspect_gguf
            metadata = await asyncio.to_thread(inspect_gguf, path.expanduser())
            self.authorize(session_id)
            try:
                record = self.models.register(path, metadata)
            except OSError:
                raise AIError('모델 파일을 읽을 수 없습니다. 경로와 권한을 확인해 주세요.') from None
            self.error = ''
            self.notify()
            return record

    async def download(self, session_id, model_id):
        self.authorize(session_id)
        if not self.settings.enabled or not self.runtime.supported:
            raise AIError('AI 사용을 켠 뒤 다운로드해 주세요.')
        if self.download_task or self._mutation.locked():
            raise AIError('다른 모델 작업이 진행 중입니다.')
        item = next((item for item in catalog() if item.id == model_id), None)
        if item is None:
            raise AIError('추천 목록의 모델을 선택해 주세요.')
        self.download_task = asyncio.current_task()
        self.download_id, self.downloaded, self.total = item.id, 0, item.size
        self.error = ''
        self.notify()
        try:
            await self.models.download(item, self._progress)
        except AIError as error:
            self.error = str(error)
            raise
        finally:
            self.download_task = None
            self.download_id = None
            self.notify()

    def _progress(self, downloaded, total):
        self.downloaded, self.total = downloaded, total
        now = time.monotonic()
        if now - self._last_progress >= .2 or downloaded == total:
            self._last_progress = now
            self.notify()

    def save_harness(self, session_id, definition):
        self.authorize(session_id)
        result = self.harnesses.save(definition)
        self.notify()
        return result

    def duplicate_harness(self, session_id, definition):
        self.authorize(session_id)
        result = self.harnesses.duplicate(definition)
        self.notify()
        return result

    def delete_harness(self, session_id, key):
        self.authorize(session_id)
        self.harnesses.delete(key)
        self.notify()

    @asynccontextmanager
    async def _generation_scope(self, session_id):
        self.authorize(session_id)
        if not self.settings.enabled:
            raise AIError('AI 사용이 꺼져 있습니다.')
        if self.generation or self._mutation.locked():
            raise AIError('다른 AI 작업이 진행 중입니다.')
        record = self.models.records.get(self.settings.selected_model_id)
        if record is None:
            raise AIError('사용할 모델을 선택해 주세요.')
        self.generation, self.owner = asyncio.current_task(), session_id
        revision = self.revision
        self.loading, self.error = True, ''
        self.notify()
        def check():
            self.authorize(session_id)
            if revision != self.revision or not self.settings.enabled:
                raise asyncio.CancelledError()
        try:
            await self.runtime.ensure_loaded(record)
            check()
            self.models.mark_verified(record.id)
            self.loading = False
            self.notify()
            yield record, check
            check()
        except AIError as error:
            self.error = str(error)
            await self.runtime.stop()
            raise
        except BaseException:
            await self.runtime.stop()
            raise
        finally:
            self.generation = self.owner = None
            self.loading = False
            self.notify()

    async def generate(self, session_id: str, request: GenerationRequest, emit):
        self.authorize(session_id)
        if not request.prompt.strip() or len(request.prompt) > 12000 or not 1 <= request.max_tokens <= 512:
            raise AIError('테스트 입력은 1~12,000자, 출력은 최대 512토큰으로 제한합니다.')
        reasoning = self.settings.reasoning_enabled
        async with self._generation_scope(session_id) as (record, check):
            request = replace(request, reasoning_enabled=reasoning and supports_reasoning(record))
            async for event in self.runtime.generate(record, request):
                check()
                emit(event)

    async def run_harness(self, session_id, definition, note):
        # UI가 편집 중이어도 실행 시점의 독립된 정의를 유지한다.
        definition = parse_definition(definition.model_dump_json())
        if not note.strip() or len(note) > 12000:
            raise AIError('시험 입력은 1~12,000자로 작성하세요.')
        async with self._generation_scope(session_id) as (record, check):
            async def generate(request):
                check()
                await self.runtime.check_context(record, request)
                check()
                chunks, done = [], False
                async for event in self.runtime.generate(record, request):
                    check()
                    if event.kind == 'text':
                        chunks.append(event.text)
                    elif event.kind == 'done':
                        done = True
                check()
                if not done:
                    raise AIError('AI 응답이 중간에 종료되었습니다. 다시 시도해 주세요.')
                return ''.join(chunks)
            result = await run_harness_workflow(definition, note, generate)
            check()
            return result

    async def cancel(self, session_id):
        self.authorize(session_id)
        if self.owner == session_id:
            await self._cancel_generation()
            self.notify()

    async def detach(self, session_id, *, lock=False):
        self.sessions.pop(session_id, None)
        async with self._mutation:
            if lock or self.owner == session_id or not self.sessions:
                await self._cancel_generation()
            if not self.sessions:
                await self.cancel_download()
            self.notify()

    async def close(self):
        self.sessions.clear()
        await self._cancel_generation()
        await self.cancel_download()
        self.notify()
