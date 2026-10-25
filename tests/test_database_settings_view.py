"""DB 탭에서 백업 다운로드와 파일 업로드 복원 흐름을 검사한다."""

import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseOpenError
from maeumnarae.core.models import StudentInput
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.services.database_maintenance import create_backup
from maeumnarae.views.database_settings_view import build_database_settings


def callback(button):
    listener = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
    return inspect.getclosurevars(listener).nonlocals['callback']


class DatabaseSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_folder_download_and_restore_require_confirmation_and_valid_password(self):
        async def inline(function, *args):
            return function(*args)

        with TemporaryDirectory() as directory, Client(page('/database-settings-test')) as client:
            database = Database('current-key', Path(directory) / 'current.db')
            database.initialize()
            source = Database('backup-key', Path(directory) / 'source.db')
            source.initialize()
            StudentRepository(source).create(StudentInput(name='Restored', grade=1, classroom='1'))
            content = create_backup(source)
            build_database_settings(database)
            elements = list(client.elements.values())
            buttons = {e.text: e for e in elements if isinstance(e, ui.button)}
            self.assertIn('일지 XLSX 만들기', buttons)
            self.assertIn('XLSX 다운로드', buttons)
            upload = next(e for e in elements if isinstance(e, ui.upload))
            password = next(e for e in elements if isinstance(e, ui.input))
            confirm = next(e for e in elements if isinstance(e, ui.checkbox))
            restore = callback(buttons['복원'])
            with patch('maeumnarae.views.database_settings_view.run.io_bound', side_effect=inline), \
                    patch('maeumnarae.views.database_settings_view.ui.notify') as notify, \
                    patch('maeumnarae.views.database_settings_view.ui.download.content') as download:
                self.assertNotIn('DB 정보 새로고침', buttons)
                self.assertFalse(any(isinstance(e, ui.label) and e.text == 'DB 정보' for e in elements))
                with patch('maeumnarae.views.database_settings_view.open_folder') as open_folder:
                    await callback(buttons['DB 폴더 열기'])()
                    open_folder.assert_called_once_with(database.path.resolve().parent)
                with patch('maeumnarae.views.database_settings_view.open_folder', side_effect=OSError):
                    await callback(buttons['DB 폴더 열기'])()
                    self.assertTrue(buttons['DB 폴더 열기'].enabled)
                    self.assertIn('DB 폴더를 열지 못했습니다', notify.call_args.args[0])
                await callback(buttons['DB 백업 다운로드'])()
                self.assertNotEqual(download.call_args.args[0][:16], b'SQLite format 3\x00')
                await restore()
                notify.assert_called()
                await upload._upload_handlers[0](SimpleNamespace(
                    file=SimpleNamespace(read=AsyncMock(return_value=content), size=lambda: len(content))))
                confirm.value = True
                password.value = 'wrong'
                await restore()
                self.assertEqual(StudentRepository(database).list(), [])
                self.assertEqual(password.value, '')
                self.assertTrue(buttons['복원'].enabled)
                password.value = 'backup-key'
                await restore()
                self.assertFalse(buttons['복원'].enabled)
                with self.assertRaises(DatabaseOpenError):
                    StudentRepository(database).list()
                restored = Database('backup-key', database.path)
                self.assertEqual(StudentRepository(restored).list()[0].name, 'Restored')
                self.assertTrue(any(isinstance(e, ui.button) and e.text == 'DB 다시 열기'
                                    for e in client.elements.values()))


class OpenFolderTests(unittest.TestCase):
    def test_uses_platform_file_manager_without_shell(self):
        from maeumnarae.core.desktop import open_folder
        with TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            for platform, command in [('darwin', 'open'), ('linux', 'xdg-open')]:
                with self.subTest(platform=platform), patch('maeumnarae.core.desktop.sys.platform', platform), \
                        patch('maeumnarae.core.desktop.subprocess.run') as launch:
                    open_folder(folder)
                    self.assertEqual(launch.call_args.args[0], [command, str(folder)])
                    self.assertTrue(launch.call_args.kwargs['check'])
            with patch('maeumnarae.core.desktop.sys.platform', 'win32'), patch('maeumnarae.core.desktop.os.startfile', create=True) as launch:
                open_folder(folder)
                launch.assert_called_once_with(str(folder))
