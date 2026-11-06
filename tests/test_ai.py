"""로컬 AI의 파일 소유권, 취소, 세션과 스트리밍 경계를 검증한다."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import httpx

from maeumnarae.services.ai.gguf import inspect_gguf
from maeumnarae.services.ai.models import ModelManager, catalog
from maeumnarae.services.ai.runtime import LlamaServerRuntime, request_payload
from maeumnarae.services.ai.service import AIService
from maeumnarae.services.ai.types import AIError, GenerationEvent, GenerationRequest, ModelRecord


def gguf(architecture='exaone', split=1):
    def string(value):
        data = value.encode(); return struct.pack('<Q', len(data)) + data
    metadata = [('general.architecture', 8, string(architecture)),
                ('tokenizer.chat_template', 8, string('{{ messages }}')),
                ('split.count', 4, struct.pack('<I', split))]
    return b'GGUF' + struct.pack('<IQQ', 3, 1, len(metadata)) + b''.join(
        string(key) + struct.pack('<I', kind) + value for key, kind, value in metadata) + b'\0' * 32


class FakeRuntime:
    supported = True
    backend = 'CPU'
    def __init__(self):
        self.model_id = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stops = 0
        self.fail = False
    async def ensure_loaded(self, record):
        if self.fail:
            raise AIError('시험 로딩 실패')
        self.model_id = record.id
    async def generate(self, record, request):
        self.started.set()
        yield GenerationEvent('text', '안녕')
        await self.release.wait()
        yield GenerationEvent('text', '하세요')
        yield GenerationEvent('done')
    async def stop(self):
        self.stops += 1
        self.model_id = None


class AITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = FakeRuntime()
        self.service = AIService(self.root, self.runtime)
        self.service.attach('one', lambda: True)
        self.service.attach('two', lambda: True)
        self.path = self.root / 'external.gguf'
        self.path.write_bytes(gguf())

    async def asyncTearDown(self):
        await self.service.close()

    async def ready(self):
        record = await self.service.register_model('one', self.path)
        await self.service.select_model('one', record.id)
        await self.service.set_enabled('one', True)
        return record

    async def running(self):
        await self.ready()
        self.events = []
        task = asyncio.create_task(self.service.generate('one', GenerationRequest('테스트'), self.events.append))
        await self.runtime.started.wait()
        return task

    async def test_exaone4_catalog_registration_and_legacy_profile(self):
        self.assertEqual(catalog()[0].id, 'exaone-4.0-1.2b-q4-k-m')
        self.assertFalse(any('3.5' in item.id for item in catalog()))
        self.path.write_bytes(gguf('exaone4'))
        record = await self.ready()
        self.assertEqual(record.profile, 'exaone4')
        restored = AIService(self.root, FakeRuntime())
        self.assertEqual(restored.models.records[record.id].profile, 'exaone4')
        payload = request_payload(record, GenerationRequest('안녕하세요'))
        self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': False})
        legacy = request_payload(replace(record, profile='exaone'), GenerationRequest('안녕하세요'))
        self.assertIn('EXAONE', legacy['messages'][0]['content'])
        self.assertNotIn('chat_template_kwargs', legacy)

    async def test_reasoning_persists_and_is_applied_per_request(self):
        self.path.write_bytes(gguf('exaone4'))
        record = await self.ready()
        self.assertFalse(self.service.settings.reasoning_enabled)
        await self.service.set_reasoning('one', True)
        requests = []
        original_generate = self.runtime.generate
        async def capture(record, request):
            requests.append(request)
            async for event in original_generate(record, request):
                yield event
        self.runtime.generate = capture
        task = asyncio.create_task(self.service.generate('one', GenerationRequest('test'), lambda e: None))
        await self.runtime.started.wait()
        await self.service.set_reasoning('two', False)
        self.assertFalse(task.done())
        self.assertTrue(requests[0].reasoning_enabled)
        self.runtime.release.set()
        await task
        await self.service.generate('one', GenerationRequest('test'), lambda e: None)
        self.assertFalse(requests[1].reasoning_enabled)
        await self.service.set_reasoning('one', True)
        await self.service.set_enabled('one', False)
        await self.service.select_model('one', None)
        restored = AIService(self.root, FakeRuntime())
        self.assertTrue(restored.settings.reasoning_enabled)
        for profile in ('exaone4', 'qwen3'):
            payload = request_payload(replace(record, profile=profile), GenerationRequest('test', reasoning_enabled=True))
            self.assertTrue(payload['chat_template_kwargs']['enable_thinking'])
            self.assertEqual(payload['max_tokens'], 2048)
        legacy = request_payload(replace(record, profile='exaone'), GenerationRequest('test', reasoning_enabled=True))
        self.assertNotIn('chat_template_kwargs', legacy)
        self.assertEqual(legacy['max_tokens'], 512)

    async def test_reasoning_rejects_unsupported_and_preserves_on_save_error(self):
        await self.ready()  # EXAONE 3.5
        with self.assertRaises(AIError):
            await self.service.set_reasoning('one', True)
        self.path.write_bytes(gguf('exaone4'))
        old = self.service.models.records[self.service.settings.selected_model_id]
        self.service.models.records[old.id] = replace(old, profile='exaone4')
        with patch.object(self.service.store, 'update', side_effect=OSError()):
            with self.assertRaises(AIError):
                await self.service.set_reasoning('one', True)
        self.assertFalse(self.service.settings.reasoning_enabled)
        await self.service.detach('one')
        with self.assertRaises(AIError):
            await self.service.set_reasoning('one', True)

    async def test_default_and_restore(self):
        self.assertFalse(self.service.settings.enabled)
        record = await self.ready()
        restored = AIService(self.root, FakeRuntime())
        self.assertTrue(restored.settings.enabled)
        self.assertEqual(restored.settings.selected_model_id, record.id)
        self.assertFalse('테스트' in (self.root / 'ai-settings.json').read_text())

    async def test_corrupt_settings_fail_closed(self):
        (self.root / 'ai-settings.json').write_text('{')
        service = AIService(self.root, FakeRuntime())
        self.assertFalse(service.settings.enabled)
        self.assertTrue(service.error)

    async def test_save_failure_does_not_enable(self):
        with patch.object(self.service.store, 'update', side_effect=OSError()):
            with self.assertRaises(AIError):
                await self.service.set_enabled('one', True)
        self.assertFalse(self.service.settings.enabled)

    async def test_off_save_failure_still_stops(self):
        task = await self.running()
        with patch.object(self.service.store, 'update', side_effect=OSError()):
            with self.assertRaises(AIError):
                await self.service.set_enabled('one', False)
        self.assertTrue(task.cancelled())
        self.assertFalse(self.service.settings.enabled)
        self.assertIsNone(self.runtime.model_id)

    async def test_off_preserves_files_and_selection(self):
        task = await self.running()
        selected = self.service.settings.selected_model_id
        await self.service.set_enabled('two', False)
        self.assertTrue(task.cancelled())
        self.assertTrue(self.path.exists())
        self.assertEqual(self.service.settings.selected_model_id, selected)
        self.assertEqual(len(self.events), 1)

    async def test_busy_and_cross_session_cancel(self):
        task = await self.running()
        with self.assertRaises(AIError):
            await self.service.generate('two', GenerationRequest('second'), lambda e: None)
        await self.service.cancel('two')
        self.assertFalse(task.done())
        await self.service.cancel('one')
        self.assertTrue(task.cancelled())

    async def test_switch_cancels_and_lazy_loads(self):
        task = await self.running()
        await self.service.select_model('two', None)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.runtime.model_id)
        self.assertEqual(self.service.status.state, '모델 준비 필요')

    async def test_remove_selected_external_keeps_original(self):
        task = await self.running()
        await self.service.remove_model('two', self.service.settings.selected_model_id)
        self.assertTrue(task.cancelled())
        self.assertTrue(self.path.is_file())
        self.assertIsNone(self.service.settings.selected_model_id)

    async def test_lock_discards_late_response(self):
        task = await self.running()
        await self.service.detach('one', lock=True)
        self.runtime.release.set()
        self.assertTrue(task.cancelled())
        self.assertEqual(len(self.events), 1)
        with self.assertRaises(AIError):
            await self.service.set_enabled('one', True)

    async def test_generation_checks_actual_db_state(self):
        await self.ready()
        self.service.attach('one', lambda: False)
        with self.assertRaises(AIError):
            await self.service.generate('one', GenerationRequest('private'), lambda e: None)

    async def test_completion_and_profile_isolation(self):
        record = await self.ready()
        self.runtime.release.set()
        events = []
        await self.service.generate('one', GenerationRequest('테스트'), events.append)
        self.assertEqual(events[-1].kind, 'done')
        self.assertTrue(self.service.models.records[record.id].verified)
        payload = request_payload(record, GenerationRequest('test'))
        self.assertIn('EXAONE', payload['messages'][0]['content'])
        self.assertNotIn('chat_template_kwargs', payload)
        qwen = request_payload(replace(record, profile='qwen3'), GenerationRequest('test'))
        self.assertEqual(qwen['chat_template_kwargs'], {'enable_thinking': False})
        self.assertNotIn('EXAONE', qwen['messages'][0]['content'])

    async def test_load_error_retry(self):
        await self.ready()
        self.runtime.fail = True
        with self.assertRaises(AIError):
            await self.service.generate('one', GenerationRequest('test'), lambda e: None)
        self.assertIsNone(self.service.generation)
        self.assertTrue(self.service.error)
        self.runtime.fail = False; self.runtime.release.set()
        await self.service.generate('one', GenerationRequest('test'), lambda e: None)
        self.assertFalse(self.service.error)

    async def test_register_duplicate_and_invalid(self):
        first = await self.service.register_model('one', self.path)
        second = await self.service.register_model('one', self.path)
        self.assertEqual(first.id, second.id)
        self.path.write_bytes(b'not gguf')
        with self.assertRaises(AIError):
            inspect_gguf(self.path)
        for arch, split in [('clip', 1), ('exaone', 2)]:
            self.path.write_bytes(gguf(arch, split))
            with self.assertRaises(AIError):
                inspect_gguf(self.path)

    async def test_managed_path_escape_never_deletes_external(self):
        record = await self.service.register_model('one', self.path)
        self.service.models.records[record.id] = replace(record, managed=True)
        with self.assertRaises(AIError):
            self.service.models.remove(record.id)
        self.assertTrue(self.path.exists())

    async def test_valid_download_and_managed_delete(self):
        content = gguf()
        item = replace(catalog()[0], size=len(content), sha256=hashlib.sha256(content).hexdigest())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
            record = await self.service.models.download(item, lambda *args: None, client)
        self.assertTrue(record.managed)
        self.assertFalse(record.verified)
        self.service.models.remove(record.id)
        self.assertFalse(Path(record.path).exists())

    async def test_download_hash_error_no_partial_registration(self):
        content = gguf()
        item = replace(catalog()[0], size=len(content), sha256='0' * 64)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
            with self.assertRaises(AIError):
                await self.service.models.download(item, lambda *args: None, client)
        self.assertFalse(self.service.models.records)
        self.assertEqual(list(self.service.models.directory.iterdir()), [])

    async def test_download_space_error(self):
        with patch('maeumnarae.services.ai.models.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(AIError):
                await self.service.models.download(catalog()[0], lambda *args: None)

    async def test_download_off_cancels(self):
        await self.service.set_enabled('one', True)
        started = asyncio.Event()
        async def stalled(*args):
            started.set()
            await asyncio.Event().wait()
        with patch.object(self.service.models, 'download', stalled):
            task = asyncio.create_task(self.service.download('one', catalog()[0].id))
            await started.wait()
            with self.assertRaises(AIError):
                await self.service.download('two', catalog()[1].id)
            await self.service.set_enabled('two', False)
            self.assertTrue(task.cancelled())
            self.assertIsNone(self.service.download_id)

    async def test_reasoning_stream_separates_thoughts_and_answer(self):
        cases = [
            ([{'reasoning_content': '검토'}, {'reasoning_content': ' 중'}, {'content': '답변'}], False),
            ([{'content': '<thi'}, {'content': 'nk>검토 '}, {'content': '중</th'},
              {'content': 'ink>답변'}], True),
        ]
        for deltas, thinking in cases:
            text = ''.join('data: ' + json.dumps({'choices': [{'delta': delta}]}) + '\n\n'
                           for delta in deltas) + 'data: [DONE]\n\n'
            runtime = LlamaServerRuntime()
            runtime.client = httpx.AsyncClient(base_url='http://127.0.0.1', transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text=text)))
            try:
                events = [e async for e in runtime.generate(ModelRecord('id', 'n', '', 1),
                          GenerationRequest('test', reasoning_enabled=thinking))]
                self.assertEqual(''.join(e.text for e in events if e.kind == 'reasoning'), '검토 중')
                self.assertEqual(''.join(e.text for e in events if e.kind == 'text'), '답변')
                self.assertEqual(events[-1].kind, 'done')
            finally:
                await runtime.stop()

    async def test_think_parser_handles_each_character_and_unclosed_thought(self):
        from maeumnarae.services.ai.reasoning import ThinkStreamSplitter
        parser = ThinkStreamSplitter()
        events = []
        for char in '<think>검토</think>답변<think>추가 검토':
            events.extend(parser.feed(char))
        events.extend(parser.feed('', final=True))
        self.assertEqual(''.join(e.text for e in events if e.kind == 'reasoning'), '검토추가 검토')
        self.assertEqual(''.join(e.text for e in events if e.kind == 'text'), '답변')

    async def test_stream_parser(self):
        runtime = LlamaServerRuntime()
        text = 'data: {"choices":[{"delta":{"content":"안녕"}}]}\n\ndata: [DONE]\n\n'
        runtime.client = httpx.AsyncClient(base_url='http://127.0.0.1', transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text=text)))
        record = ModelRecord('id', 'name', str(self.path), 1)
        try:
            events = [e async for e in runtime.generate(record, GenerationRequest('test'))]
            self.assertEqual([(e.kind, e.text) for e in events], [('text', '안녕'), ('done', '')])
        finally:
            await runtime.stop()

    async def test_stream_truncation_and_http_error(self):
        for response in [httpx.Response(200, text='data: {"choices":[]}\n'), httpx.Response(500)]:
            runtime = LlamaServerRuntime()
            runtime.client = httpx.AsyncClient(base_url='http://127.0.0.1', transport=httpx.MockTransport(lambda r: response))
            try:
                with self.assertRaises(AIError):
                    _ = [e async for e in runtime.generate(ModelRecord('id', 'n', '', 1), GenerationRequest('test'))]
            finally:
                await runtime.stop()


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_guard_closes_child_on_pipe_eof(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'pid'
            child_code = 'import os,time,pathlib;pathlib.Path(__import__("sys").argv[1]).write_text(str(os.getpid()));time.sleep(60)'
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'maeumnarae.services.ai.guard', '--ai-engine-guard',
                sys.executable, '-c', child_code, str(marker), stdin=asyncio.subprocess.PIPE)
            try:
                process.stdin.write(b'test-key\n'); await process.stdin.drain()
                async with asyncio.timeout(5):
                    while not marker.exists():
                        await asyncio.sleep(.02)
                process.stdin.close()
                await asyncio.wait_for(process.wait(), 5)
                self.assertIsNotNone(process.returncode)
            finally:
                if process.returncode is None:
                    process.stdin.close()
                    await asyncio.wait_for(process.wait(), 5)

    @unittest.skipIf(__import__('sys').platform == 'win32', 'POSIX PID existence probe')
    async def test_parent_crash_reaps_engine(self):
        import os
        import sys
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'child.pid'
            child_code = 'import os,time,pathlib,sys;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)'
            parent_code = '''import subprocess,sys,time
p=subprocess.Popen([sys.executable,'-m','maeumnarae.services.ai.guard','--ai-engine-guard',sys.executable,'-c',sys.argv[1],sys.argv[2]],stdin=subprocess.PIPE)
p.stdin.write(b'test-key\\n');p.stdin.flush()
time.sleep(60)
'''
            process = await asyncio.create_subprocess_exec(sys.executable, '-c', parent_code, child_code, str(marker))
            try:
                async with asyncio.timeout(5):
                    while not marker.exists():
                        await asyncio.sleep(.02)
                child_pid = int(marker.read_text())
                process.kill(); await process.wait()
                async with asyncio.timeout(5):
                    while True:
                        try:
                            os.kill(child_pid, 0)
                        except ProcessLookupError:
                            break
                        await asyncio.sleep(.02)
            finally:
                if process.returncode is None:
                    process.kill(); await process.wait()


class DownloadFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_cleans_partial_file(self):
        started = asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'x' * (1024 * 1024)
                started.set()
                await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as directory:
            manager = ModelManager(Path(directory))
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))) as client:
                task = asyncio.create_task(manager.download(catalog()[0], lambda *a: None, client))
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertFalse(manager.records)
            self.assertFalse(list(manager.directory.glob('*.part')))

    async def test_network_failure_cleans_partial_file(self):
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'x' * (1024 * 1024)
                raise httpx.ReadError('private network details')
        with tempfile.TemporaryDirectory() as directory:
            manager = ModelManager(Path(directory))
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))) as client:
                with self.assertRaises(AIError) as caught:
                    await manager.download(catalog()[0], lambda *a: None, client)
            self.assertNotIn('private', str(caught.exception))
            self.assertFalse(manager.records)
            self.assertFalse(list(manager.directory.glob('*.part')))

    async def test_missing_model_and_metal_fallback(self):
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.gguf'
            path.write_bytes(gguf())
            executable = Path(directory) / 'llama-server'
            executable.touch()
            runtime = LlamaServerRuntime()
            record = ModelRecord('id', 'n', str(path), path.stat().st_size)
            with patch('maeumnarae.services.ai.runtime.engine_path', return_value=executable), \
                 patch('maeumnarae.services.ai.runtime.sys.platform', 'darwin'):
                runtime._start = AsyncMock(side_effect=[AIError('Metal unavailable'), None])
                await runtime.ensure_loaded(record)
                self.assertEqual([call.args[2] for call in runtime._start.await_args_list], [True, False])
                path.unlink()
                with self.assertRaises(AIError):
                    await runtime.ensure_loaded(record)


if __name__ == '__main__':
    unittest.main()
