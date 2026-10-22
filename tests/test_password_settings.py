"""실제 SQLCipher 키 변경과 변경 폼의 검증·중복 실행 방지."""

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database, DatabaseError, DatabaseOpenError
from models import StudentInput
from repositories.student_repo import StudentRepository
from views.password_settings_view import build_password_settings


@pytest.fixture
def database(tmp_path):
    db = Database("old-'비밀번호", tmp_path / 'password.db')
    db.initialize()
    StudentRepository(db).create(StudentInput(name='보존할 학생', grade=3, classroom='1'))
    return db


def test_rekey_preserves_data_and_rejects_old_password(database):
    new = " new-'비밀번호 ; DROP TABLE students; -- "
    database.change_password("old-'비밀번호", new)
    assert StudentRepository(database).list()[0].name == '보존할 학생'
    with pytest.raises(DatabaseOpenError):
        Database("old-'비밀번호", database.path).initialize()
    database.lock()
    reopened = Database(new, database.path)
    reopened.initialize()
    assert StudentRepository(reopened).list()[0].name == '보존할 학생'
    assert database.path.read_bytes()[:16] != b'SQLite format 3\x00'


@pytest.mark.parametrize('current,new', [
    ('wrong', 'new-secret'), ("old-'비밀번호", ''), ("old-'비밀번호", 'bad\x00key'),
    ("old-'비밀번호", "old-'비밀번호"),
])
def test_rejected_changes_keep_original_key(database, current, new):
    with pytest.raises((ValueError, DatabaseError)):
        database.change_password(current, new)
    assert len(StudentRepository(database).list()) == 1
    assert len(StudentRepository(Database("old-'비밀번호", database.path)).list()) == 1


def test_locked_database_cannot_change_password(database):
    database.lock()
    with pytest.raises(DatabaseOpenError):
        database.change_password("old-'비밀번호", 'new-secret')


def test_rekey_busy_failure_keeps_original_key(database):
    # 다른 연결이 읽기 잠금을 잡고 있을 때 실제 rekey 커밋 실패를 유도한다.
    reader = database._connect()
    writer = database._connect()
    writer.execute('PRAGMA busy_timeout=1')
    reader.execute('BEGIN')
    reader.execute('SELECT * FROM students').fetchall()
    try:
        with patch.object(database, '_connect', return_value=writer):
            with pytest.raises(DatabaseError):
                database.change_password("old-'비밀번호", 'new-secret')
    finally:
        reader.rollback()
        reader.close()
    assert len(StudentRepository(database).list()) == 1
    assert len(StudentRepository(Database("old-'비밀번호", database.path)).list()) == 1


def test_silent_rekey_failure_is_detected(database):
    connect = database._connect
    connection = connect()
    proxy = Mock(wraps=connection)

    def execute(statement):
        if statement.startswith('PRAGMA rekey'):
            return connection.execute("SELECT 'ok'")
        return connection.execute(statement)

    proxy.execute.side_effect = execute
    calls = 0

    def open_connection():
        nonlocal calls
        calls += 1
        return proxy if calls == 1 else connect()

    with patch.object(database, '_connect', side_effect=open_connection):
        with pytest.raises(DatabaseError, match='기존 비밀번호가 유지'):
            database.change_password("old-'비밀번호", 'new-secret')
    assert len(StudentRepository(database).list()) == 1


class PasswordFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_busy_and_secret_cleanup(self):
        client = Client(page('/password-settings-test'))
        client.__enter__()
        host = ui.column()
        database = Mock()
        try:
            with host:
                build_password_settings(database)
            dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog))
            fields = {e.props['label']: e for e in dialog.descendants() if isinstance(e, ui.input)}
            self.assertFalse(dialog.value)
            self.assertEqual(len(fields), 3)
            self.assertFalse(any(isinstance(e, ui.input) for e in host.descendants()))
            button = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '변경')
            cancel = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '취소')
            listener = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            change = inspect.getclosurevars(listener).nonlocals['callback']
            release = asyncio.Event()

            async def slow_change(*args):
                await release.wait()

            with host, patch('views.password_settings_view.ui.notify'), \
                    patch('views.password_settings_view.run.io_bound', new=AsyncMock(side_effect=slow_change)) as io:
                dialog.open()
                self.assertTrue(dialog.value)
                await change()
                io.assert_not_awaited()
                fields['현재 비밀번호'].value = 'old'
                fields['새 비밀번호'].value = 'new'
                fields['새 비밀번호 확인'].value = 'mismatch'
                await change()
                io.assert_not_awaited()
                fields['새 비밀번호 확인'].value = 'new'
                task = asyncio.create_task(change())
                await asyncio.sleep(0)
                self.assertFalse(button.enabled)
                self.assertFalse(cancel.enabled)
                await change()
                io.assert_awaited_once_with(database.change_password, 'old', 'new')
                release.set()
                await task
                self.assertTrue(button.enabled)
                self.assertFalse(dialog.value)
                self.assertTrue(all(field.value == '' for field in fields.values()))

                for field in fields.values():
                    field.value = 'new' if field is not fields['현재 비밀번호'] else 'old'
                io.side_effect = DatabaseError('현재 비밀번호가 올바르지 않습니다.')
                dialog.open()
                await change()
                self.assertTrue(button.enabled)
                self.assertTrue(dialog.value)
                self.assertTrue(all(field.value == '' for field in fields.values()))

                for field in fields.values():
                    field.value = 'secret'
                cancel_listener = next(e.handler for e in cancel._event_listeners.values() if e.type == 'click')
                inspect.getclosurevars(cancel_listener).nonlocals['callback']()
                self.assertFalse(dialog.value)
                self.assertTrue(all(field.value == '' for field in fields.values()))
        finally:
            host.delete()
            client.__exit__(None, None, None)
