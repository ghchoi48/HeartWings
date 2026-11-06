"""양식 정의, 민감 데이터 비저장, 재시도와 생성 수명 경계."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
import httpx

from maeumnarae.services.ai.harness.store import HarnessStore, parse_definition
from maeumnarae.services.ai.harness.runner import run
from maeumnarae.services.ai.harness.context import build_request
from maeumnarae.services.ai.harness.validators import validate_output
from maeumnarae.services.ai.runtime import LlamaServerRuntime, request_payload
from maeumnarae.services.ai.service import AIService
from maeumnarae.services.ai.types import AIError, AISettings, GenerationEvent, GenerationRequest, ModelRecord


def output(definition, text='정리', evidence=None):
    return json.dumps({'fields': [{'id': f.id, 'text': text, 'evidence': evidence or []}
                                 for f in definition.fields]}, ensure_ascii=False)


class HarnessStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = HarnessStore(self.root)
        self.definition = next(iter(self.store.defaults.values()))

    def test_roundtrip_copy_save_delete_and_defaults(self):
        copy = self.store.duplicate(self.definition)
        self.assertNotEqual(copy.id, self.definition.id)
        self.assertEqual(parse_definition(copy.model_dump_json()), copy)
        changed = copy.model_copy(update={'name': '내 양식', 'fields': list(reversed(copy.fields))})
        self.store.save(changed)
        restored = HarnessStore(self.root)
        self.assertEqual(restored.records[copy.id], changed)
        with self.assertRaises(AIError):
            restored.save(self.definition)
        with self.assertRaises(AIError):
            restored.delete(self.definition.id)
        restored.delete(copy.id)
        self.assertFalse(HarnessStore(self.root).records)

    def test_invalid_definitions_and_corrupt_store_preserved(self):
        for edit in ({'version': 2}, {'fields': []}, {'fields': [self.definition.fields[0].model_dump()] * 2},
                     {'name': '  '}, {'script': 'arbitrary code'}):
            data = self.definition.model_dump() | edit
            with self.assertRaises(AIError):
                parse_definition(json.dumps(data))
        with self.assertRaises(AIError):
            parse_definition('x' * 65537)
        path = self.root / 'ai-harnesses.json'
        for invalid in ('{broken', '{"version":2,"definitions":[]}', '{"version":1,"definitions":null}'):
            path.write_text(invalid)
            broken = HarnessStore(self.root)
            self.assertTrue(broken.error)
            self.assertEqual(len(broken.defaults), 2)
            with self.assertRaises(AIError):
                broken.duplicate(self.definition)
            self.assertEqual(path.read_text(), invalid)

    def test_write_failure_preserves_disk_and_memory(self):
        copy = self.store.duplicate(self.definition)
        before = self.store.store.path.read_bytes()
        with patch('pathlib.Path.replace', side_effect=OSError):
            with self.assertRaises(AIError):
                self.store.delete(copy.id)
        self.assertIn(copy.id, self.store.records)
        self.assertEqual(before, self.store.store.path.read_bytes())


class HarnessRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.definition = next(iter(HarnessStore(Path(self.temp.name)).defaults.values()))

    async def test_format_retry_only_and_order(self):
        calls = []
        async def generate(request):
            calls.append(request)
            return 'bad json' if len(calls) == 1 else output(self.definition, evidence=['원문'])
        result = await run(self.definition, '원문', generate)
        self.assertTrue(result.format_valid)
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.format_errors, 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result.needs_review)
        self.assertFalse(calls[0].reasoning_enabled)
        self.assertEqual(calls[0].max_tokens, 1024)

    async def test_second_bad_format_is_reviewable_failure(self):
        async def generate(request):
            return '{"fields":[]}'
        result = await run(self.definition, '메모', generate)
        self.assertFalse(result.format_valid)
        self.assertEqual(result.format_errors, 2)
        self.assertFalse(result.fields)

    async def test_evidence_warning_does_not_retry(self):
        calls = 0
        async def generate(request):
            nonlocal calls
            calls += 1
            return output(self.definition, evidence=['없는 근거'])
        result = await run(self.definition, '원문', generate)
        self.assertEqual(calls, 1)
        self.assertTrue(all(i.code == 'unmatched_evidence' for i in result.issues))
        fields, issues = validate_output(output(self.definition, '확인 필요'), self.definition, '원문')
        self.assertTrue(all(i.code == 'missing_information' for i in issues))

    async def test_transport_error_and_cancel_do_not_retry(self):
        for error in (AIError('연결 오류'), asyncio.CancelledError()):
            calls = []
            async def generate(request):
                calls.append(request)
                raise error
            with self.assertRaises(type(error)):
                await run(self.definition, '원문', generate)
            self.assertEqual(len(calls), 1)

    async def test_missing_duplicate_unknown_and_wrong_type(self):
        valid = json.loads(output(self.definition))
        variants = [{'fields': valid['fields'][:1]}, {'fields': valid['fields'][:1] * 2},
                    {'fields': [dict(f, id='unknown') for f in valid['fields']]},
                    {'fields': [dict(f, text=123) for f in valid['fields']]}]
        for data in variants:
            with self.assertRaises(ValueError):
                validate_output(json.dumps(data), self.definition, '원문')


class Runtime:
    supported = True
    backend = 'CPU'
    def __init__(self):
        self.model_id = None
        self.requests = []
        self.wait_at = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stop_count = 0
        self.first_bad = False
        self.context_error = False
        self.definition = None
    async def ensure_loaded(self, record):
        self.model_id = record.id
    async def stop(self):
        self.stop_count += 1
    async def check_context(self, record, request):
        if self.context_error:
            raise AIError('입력 초과')
    async def generate(self, record, request):
        self.requests.append(request)
        if len(self.requests) == self.wait_at:
            self.started.set()
            await self.release.wait()
        yield GenerationEvent('text', 'bad' if len(self.requests) == 1 and self.first_bad else output(self.definition))
        yield GenerationEvent('done')


class HarnessServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Runtime()
        self.service = AIService(Path(self.temp.name), self.runtime)
        self.unlocked = True
        self.service.attach('one', lambda: self.unlocked)
        self.service.attach('two', lambda: True)
        self.service.models.records['model'] = ModelRecord('model', 'Test', '', 0, profile='exaone4')
        self.service.settings = AISettings(True, 'model', True)
        self.definition = next(iter(self.service.harnesses.defaults.values()))
        self.runtime.definition = self.definition
    async def asyncTearDown(self):
        await self.service.close()

    async def test_no_input_output_persistence_and_reasoning_off(self):
        await self.service.run_harness('one', self.definition, 'SECRET_INPUT_123')
        self.assertFalse(self.runtime.requests[0].reasoning_enabled)
        self.assertIsNone(self.service.generation)
        for path in Path(self.temp.name).rglob('*'):
            if path.is_file():
                self.assertNotIn('SECRET_INPUT_123', path.read_text())
                self.assertNotIn('정리', path.read_text())

    async def test_retry_holds_owner_and_cancel_does_not_publish(self):
        self.runtime.first_bad = True
        self.runtime.wait_at = 2
        task = asyncio.create_task(self.service.run_harness('one', self.definition, '원문'))
        await self.runtime.started.wait()
        self.assertEqual(self.service.owner, 'one')
        with self.assertRaises(AIError):
            await self.service.generate('two', GenerationRequest('메모'), lambda e: None)
        await self.service.cancel('one')
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.service.owner)
        self.assertEqual(len(self.runtime.requests), 2)

    async def test_model_off_lock_disconnect_cancel(self):
        for action in ('model', 'off', 'lock', 'disconnect'):
            self.service.settings = AISettings(True, 'model')
            self.service.attach('one', lambda: True)
            self.runtime.requests.clear()
            self.runtime.started.clear()
            self.runtime.wait_at = 1
            task = asyncio.create_task(self.service.run_harness('one', self.definition, '원문'))
            await self.runtime.started.wait()
            if action == 'model':
                await self.service.select_model('one', None)
            elif action == 'off':
                await self.service.set_enabled('one', False)
            else:
                await self.service.detach('one', lock=action == 'lock')
            self.assertTrue(task.cancelled(), action)
            self.assertIsNone(self.service.generation)

    async def test_token_overflow_prevents_generation(self):
        self.runtime.context_error = True
        with self.assertRaises(AIError):
            await self.service.run_harness('one', self.definition, '원문')
        self.assertFalse(self.runtime.requests)


class HarnessRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_uses_template_and_tokenizer(self):
        calls = []
        record = ModelRecord('test', 'test', '', 0, profile='exaone4')
        request = GenerationRequest('메모', max_tokens=1024, system_instruction='지침', output_schema={'type':'object'})
        for count, fails in ((3000, False), (3100, True)):
            def respond(req):
                data = json.loads(req.content)
                calls.append((req.url.path, data))
                if req.url.path == '/apply-template':
                    self.assertFalse(data['chat_template_kwargs']['enable_thinking'])
                    self.assertIn('지침', data['messages'][0]['content'])
                    return httpx.Response(200, json={'prompt':'RENDERED'})
                self.assertEqual(data['content'], 'RENDERED')
                return httpx.Response(200, json={'tokens':[1] * count})
            runtime = LlamaServerRuntime()
            runtime.client = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(respond))
            try:
                if fails:
                    with self.assertRaises(AIError):
                        await runtime.check_context(record, request)
                else:
                    await runtime.check_context(record, request)
            finally:
                await runtime.stop()
        self.assertEqual(len(calls), 4)

    async def test_structured_truncation_stream_end_and_unsupported(self):
        for finish, status in (('length', 200), (None, 200), ('stop', 400), ('stop', 200)):
            chunk = json.dumps({'choices':[{'delta':{'content':'{}'}, 'finish_reason':finish}]})
            raw = 'data: ' + chunk + '\n\ndata: [DONE]\n\n'
            runtime = LlamaServerRuntime()
            runtime.client = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(
                lambda req: httpx.Response(status, text=raw)))
            request = GenerationRequest('메모', output_schema={'type':'object'})
            record = ModelRecord('test','test','',0)
            try:
                if finish != 'stop' or status != 200:
                    with self.assertRaises(AIError):
                        [event async for event in runtime.generate(record, request)]
                else:
                    events = [event async for event in runtime.generate(record, request)]
                    self.assertEqual(events[-1].kind, 'done')
            finally:
                await runtime.stop()
