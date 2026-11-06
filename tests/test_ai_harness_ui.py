import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nicegui import core, ui
from nicegui.client import Client
from maeumnarae.services.ai.service import AIService
from maeumnarae.views.ai_settings_view import AISettingsView


class Database:
    is_locked = False


class HarnessUITests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_roundtrip_advanced_preview_export_and_lock(self):
        core.loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            service = AIService(Path(directory))
            database = Database()
            client = Client(ui.page('/harness-test'), request=None)
            with client:
                view = AISettingsView(service, database)
                view.build()
            try:
                h = view.harness
                with client:
                    h.duplicate()
                    key = h.selected_id
                    h.add_field()
                    new_id = h.data['fields'][-1]['id']
                    h.move(2, -1)
                    self.assertEqual(h.data['fields'][1]['id'], new_id)
                    h.edit(h.data, 'name', '내 시험 양식')
                    h.save()
                    h.note.set_value('비공개 시험 입력')
                    self.assertNotIn('비공개', h.advanced.value)
                    with patch('nicegui.ui.download') as download:
                        h.export()
                    raw = download.call_args.args[0]
                    self.assertNotIn('비공개', raw.decode())
                    self.assertEqual(json.loads(raw)['name'], '내 시험 양식')
                    h.advanced.set_value(json.dumps(dict(h.data, name='JSON에서 수정')))
                    h.apply_json(); h.save()
                    self.assertEqual(service.harnesses.records[key].name, 'JSON에서 수정')
                    h.note.set_value('화면을 나가면 지워질 입력')
                    view.task_tabs.set_value('작업 양식')
                    view.task_tabs.set_value('작동 확인')
                    self.assertEqual(h.note.value, '')
                    h.note.set_value('상위 화면 종료 입력')
                    view.leave()
                    self.assertEqual(h.note.value, '')
                    self.assertEqual(h.data['name'], 'JSON에서 수정')
                    h.import_dialog()
                    self.assertEqual(len(h.dialogs), 1)
                restored = AIService(Path(directory))
                self.assertEqual(restored.harnesses.records[key].fields[1].id, new_id)
                await restored.close()
                h.note.set_value('세션 해제 후 잠금에서도 지울 입력')
                await service.detach(view.session, lock=True)
                database.is_locked = True
                await view.check_lock()
                self.assertEqual(h.note.value, '')
                self.assertIsNone(h.result)
                self.assertEqual(len(h.results.default_slot.children), 0)
                from maeumnarae.services.ai.types import AIError
                with self.assertRaises(AIError):
                    service.save_harness(view.session, h.definition())
            finally:
                await view.delete()
                client.delete()
                await service.close()
                await asyncio.sleep(.02)

    async def test_late_result_after_leaving_is_not_displayed(self):
        from unittest.mock import AsyncMock
        from maeumnarae.services.ai.harness.types import HarnessRunResult
        core.loop = asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory:
            service = AIService(Path(directory))
            client = Client(ui.page('/harness-late'), request=None)
            started, release = asyncio.Event(), asyncio.Event()
            async def respond(*args):
                started.set()
                await release.wait()
                return HarnessRunResult(fields=[], issues=[], raw_json='PRIVATE_OUTPUT',
                    elapsed_seconds=1.0, retries=0, format_errors=0, format_valid=True)
            service.run_harness = AsyncMock(side_effect=respond)
            with client:
                view = AISettingsView(service, Database())
                view.build()
                view.harness.note.set_value('PRIVATE_INPUT')
                task = asyncio.create_task(view.harness.run())
            try:
                await started.wait()
                with client:
                    view.leave()
                release.set()
                await task
                self.assertIsNone(view.harness.result)
                self.assertEqual(view.harness.note.value, '')
                texts = [getattr(element, 'text', '') for element in client.elements.values()]
                self.assertNotIn('PRIVATE_OUTPUT', texts)
            finally:
                await view.delete()
                client.delete()
                await service.close()
                await asyncio.sleep(.02)
