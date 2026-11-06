import asyncio
from pathlib import Path
import tempfile
import unittest

from nicegui import core, ui
from nicegui.client import Client
from maeumnarae.services.ai.service import AIService
from maeumnarae.views.ai_settings_view import AISettingsView


class Database:
    is_locked = False


class AIUITests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_sync_and_lock_clears_text(self):
        core.loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            service = AIService(Path(directory))
            database = Database()
            clients = [Client(ui.page('/ai-test'), request=None) for _ in range(2)]
            views = []
            try:
                for client in clients:
                    with client:
                        view = AISettingsView(service, database)
                        view.build(); views.append(view)
                if service.runtime.supported:
                    await service.set_enabled(clients[0].id, True)
                    await asyncio.sleep(.02)
                    self.assertTrue(all(v.toggle.value for v in views))
                    from maeumnarae.services.ai.types import ModelRecord
                    service.models.records['thinking'] = ModelRecord('thinking', 'EXAONE 4', '', 0, profile='exaone4')
                    await service.select_model(clients[0].id, 'thinking')
                    await service.set_reasoning(clients[0].id, True)
                    await asyncio.sleep(.02)
                    self.assertTrue(all(v.reasoning_toggle.value for v in views))
                    await service.set_enabled(clients[1].id, False)
                    await asyncio.sleep(.02)
                    self.assertTrue(all(not v.toggle.value for v in views))
                views[0].output.set_text('비공개 테스트')
                views[0].prompt.set_value('입력')
                database.is_locked = True
                await views[0].check_lock()
                self.assertEqual(views[0].output.text, '')
                self.assertEqual(views[0].prompt.value, '')
            finally:
                for view in views:
                    await view.delete()
                for client in clients:
                    client.delete()
                await service.close()
                await asyncio.sleep(.02)

    async def test_chat_keeps_bubbles_and_clears_all_on_lock(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from maeumnarae.services.ai.types import AISettings, ModelRecord, GenerationEvent

        core.loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            runtime = SimpleNamespace(supported=True, model_id=None, backend='', stop=AsyncMock())
            service = AIService(Path(directory), runtime)
            service.settings = AISettings(True, 'test')
            service.models.records['test'] = ModelRecord('test', '시험 모델', '', 0)
            database = Database()
            client = Client(ui.page('/chat-test'), request=None)
            async def respond(session, request, emit):
                emit(GenerationEvent('reasoning', '검토 내용'))
                self.assertFalse(any(element.tag in {'details', 'summary'}
                                     for element in client.elements.values()))
                emit(GenerationEvent('reasoning', ' 추가'))
                emit(GenerationEvent('text', '응답: '))
                emit(GenerationEvent('text', request.prompt))
                emit(GenerationEvent('done'))
            service.generate = AsyncMock(side_effect=respond)
            with client:
                view = AISettingsView(service, database)
                view.build()
            try:
                for text in ('첫 메시지', '<b>두 번째 메시지</b>'):
                    view.prompt.set_value(text)
                    with client:
                        await view.generate()
                    self.assertEqual(view.prompt.value, '')
                    self.assertEqual(view.output.text, '응답: ' + text)
                texts = [element.text for element in client.elements.values() if isinstance(element, ui.label)]
                self.assertIn('검토 내용 추가', texts)
                self.assertIn('첫 메시지', texts)
                self.assertIn('응답: 첫 메시지', texts)
                self.assertIn('<b>두 번째 메시지</b>', texts)
                bubbles = [element for element in client.elements.values()
                           if isinstance(element, ui.chat_message)]
                self.assertEqual([bubble._props['sent'] for bubble in bubbles], [True, False, True, False])
                self.assertEqual([bubble._props['name'] for bubble in bubbles], ['나', 'AI', '나', 'AI'])
                self.assertEqual(service.generate.await_count, 2)
                with client:
                    await view.generate()  # 빈 입력은 전송하지 않는다.
                self.assertEqual(service.generate.await_count, 2)
                database.is_locked = True
                await view.check_lock()
                texts = [element.text for element in client.elements.values() if isinstance(element, ui.label)]
                self.assertNotIn('검토 내용 추가', texts)
                self.assertNotIn('첫 메시지', texts)
                self.assertNotIn('응답: 첫 메시지', texts)
                self.assertFalse(any(isinstance(element, ui.chat_message)
                                     for element in client.elements.values()))
                self.assertEqual(view.output.text, '')
            finally:
                await view.delete()
                client.delete()
                await service.close()
                await asyncio.sleep(.02)
