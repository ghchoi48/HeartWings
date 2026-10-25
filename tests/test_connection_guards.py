"""암호화 경계, 안전한 업로드, 비밀번호 정책과 기존 데이터 호환성 검증."""

import asyncio
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from maeumnarae.core.database import Database, DatabaseError, DatabaseOpenError, default_database_path
from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.core.secure_upload import receive_memory_upload, MULTIPART_OVERHEAD
from maeumnarae.repositories.home_repo import HomeRepository
from maeumnarae.services.database_maintenance import create_backup, restore_backup

class ConnectionGuardTests(unittest.TestCase):
    def test_plain_sqlite_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('maeumnarae.core.database.import_module', return_value=sqlite3):
                database = Database('test-only', Path(directory) / 'test.db')
            with self.assertRaises(DatabaseOpenError):
                database.initialize()

    def test_missing_driver_has_no_fallback(self):
        with patch('maeumnarae.core.database.import_module', side_effect=ImportError):
            with self.assertRaises(DatabaseError):
                Database('test-only')

    def test_password_rejects_empty_and_nul(self):
        for password in ('', 'bad\x00password'):
            with self.assertRaises(ValueError):
                Database(password)

    def test_default_path_is_absolute(self):
        self.assertTrue(default_database_path().is_absolute())


def database(path, password='test-secret'):
    db = Database(password, path)
    db.initialize()
    return db


def legacy_widgets():
    return dict(layout=[], notes={'memo': 'PRIVATE_NOTE'}, todos=[
        dict(id=1, title='PRIVATE_TODO', done=0)], next_todo_id=2)


def test_plaintext_migration_database_isolation_lock_and_backup(tmp_path):
    store = SettingsStore(tmp_path / 'display-settings.json')
    store.update(lambda data: data.update(mode='dark', widgets=legacy_widgets()))
    first = database(tmp_path / 'a.db')
    repo = HomeRepository(first, store)
    assert repo.note('memo') == 'PRIVATE_NOTE'
    assert repo.todos()[0]['title'] == 'PRIVATE_TODO'
    assert store.read() == {'mode': 'dark'}
    assert b'PRIVATE_NOTE' not in first.path.read_bytes()
    assert b'PRIVATE_TODO' not in first.path.read_bytes()
    second = database(tmp_path / 'b.db', 'other-key')
    assert HomeRepository(second, store).note('memo') == ''
    assert HomeRepository(second, store).todos() == []
    backup = create_backup(first)
    target = database(tmp_path / 'restored.db')
    restore_backup(target, backup, 'test-secret')
    assert HomeRepository(Database('test-secret', target.path)).note('memo') == 'PRIVATE_NOTE'
    repo.note_drafts['memo'] = 'unsaved secret'
    first.lock()
    with pytest.raises(DatabaseError):
        repo.note('memo')
    with pytest.raises(DatabaseError):
        repo.todos()
    with pytest.raises(DatabaseError):
        repo.add_todo('denied')


def test_interrupted_cleanup_does_not_copy_secrets_to_another_database(tmp_path):
    store = SettingsStore(tmp_path / 'display-settings.json')
    store.update(lambda data: data.update(widgets=legacy_widgets()))
    first = database(tmp_path / 'a.db')
    original_update = store.update
    calls = 0

    def fail_cleanup(change):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('cleanup failed')
        return original_update(change)

    with patch.object(store, 'update', side_effect=fail_cleanup):
        with pytest.raises(DatabaseError):
            HomeRepository(first, store).note('memo')
    second = database(tmp_path / 'b.db')
    assert HomeRepository(second, store).note('memo') == ''
    assert HomeRepository(first, store).note('memo') == 'PRIVATE_NOTE'
    assert 'widgets' not in store.read()


@pytest.mark.parametrize('secret', ['a', 'ab', 'abc'])
def test_short_new_password_rejected_without_creating_file(tmp_path, secret):
    db = Database(secret, tmp_path / 'new.db')
    with pytest.raises(ValueError, match='4글자'):
        db.initialize()
    assert not db.path.exists()


def test_four_characters_and_old_short_password_compatibility(tmp_path):
    db = database(tmp_path / 'old.db', '가나다라')
    # 이전 버전으로 만들어진 짧은 키 DB를 재현한다.
    connection = db._connect()
    connection.execute("PRAGMA rekey = 'old'")
    connection.close()
    old = Database('old', db.path)
    old.initialize()
    with pytest.raises(ValueError, match='4글자'):
        old.change_password('old', 'new')
    old.change_password('old', '1234')
    Database('1234', db.path).initialize()


def request_for(parts, *, claimed_size=None, chunk_size=32768):
    boundary = 'security-test-boundary'
    content = b''.join(
        b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="file"; filename="test.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n' + part + b'\r\n' for part in parts
    ) + b'--' + boundary.encode() + b'--\r\n'
    offset = 0

    async def receive():
        nonlocal offset
        chunk = content[offset:offset + chunk_size]
        offset += len(chunk)
        return dict(type='http.request', body=chunk, more_body=offset < len(content))

    headers = [(b'content-type', f'multipart/form-data; boundary={boundary}'.encode())]
    if claimed_size is not None:
        headers.append((b'content-length', str(claimed_size).encode()))
    return Request(dict(type='http', method='POST', path='/', headers=headers), receive)


def test_large_plaintext_upload_never_creates_a_disk_file():
    async def check():
        content = b'SYNTHETIC_PRIVATE_DATA' * 100000
        with patch('tempfile.TemporaryFile', side_effect=AssertionError('disk spool forbidden')), \
                patch('tempfile.NamedTemporaryFile', side_effect=AssertionError('disk file forbidden')):
            uploaded = await receive_memory_upload(request_for([content]), len(content))
            assert await uploaded.read() == content
    asyncio.run(check())


@pytest.mark.parametrize('claimed_size', [None, 1])
def test_oversize_file_rejected_even_without_honest_content_length(claimed_size):
    async def check():
        with pytest.raises(HTTPException) as error:
            await receive_memory_upload(request_for([b'x' * 1025], claimed_size=claimed_size), 1024)
        assert error.value.status_code == 413
    asyncio.run(check())


def test_header_limit_and_multiple_files_rejected():
    async def check():
        for request, status in [(request_for([b'a'], claimed_size=1025 + MULTIPART_OVERHEAD), 413),
                                (request_for([b'a', b'b']), 400)]:
            with pytest.raises(HTTPException) as error:
                await receive_memory_upload(request, 1024)
            assert error.value.status_code == status
    asyncio.run(check())


def test_restore_service_rejects_oversize_before_writes(tmp_path):
    db = database(tmp_path / 'app.db')
    before = db.path.read_bytes()
    with patch('maeumnarae.services.database_maintenance.MAX_BACKUP_BYTES', 8):
        with pytest.raises(DatabaseError, match='256MB'):
            restore_backup(db, b'x' * 9, 'test-secret')
    assert db.path.read_bytes() == before
    assert not (tmp_path / 'backups').exists()


def test_upload_route_replaces_default_and_waits_for_handlers():
    from nicegui import Client, app, ui
    from nicegui.page import page
    from maeumnarae.core.secure_upload import SecureUpload

    async def check():
        seen = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(event):
            seen.append(await event.file.read())
            ui.label('uploaded')  # handler의 UI 슬롯도 유지되어야 한다.
            entered.set()
            await release.wait()

        with Client(page('/secure-upload-test')) as client:
            upload = SecureUpload(max_file_size=1024, multiple=True, on_upload=handler)
            routes = [route for route in app.routes if getattr(route, 'path', None) == upload._registered_url]
            assert len(routes) == 1
            assert upload.props['batch'] is True
            endpoint = routes[0].endpoint
            first = asyncio.create_task(endpoint(request_for([b'first', b'second'])))
            await entered.wait()
            with pytest.raises(HTTPException) as busy:
                await endpoint(request_for([b'concurrent']))
            assert busy.value.status_code == 429
            release.set()
            assert await first == {'upload': 'success'}
            assert seen == [b'first', b'second']
            with pytest.raises(HTTPException) as large:
                await endpoint(request_for([b'x' * 1025]))
            assert large.value.status_code == 413
            assert await endpoint(request_for([b'after-error'])) == {'upload': 'success'}
            upload.disable()
            with pytest.raises(HTTPException) as disabled:
                await endpoint(request_for([b'disabled']))
            assert disabled.value.status_code == 403
            client.delete()
    asyncio.run(check())


def test_xlsb_import_reads_real_biff_records_without_temporary_files():
    import struct
    from zipfile import ZipFile, ZIP_DEFLATED
    from pyxlsb import biff12
    from maeumnarae.services.legacy_import import PERSON_HEADERS, LOG_HEADERS, read_rows

    def string(value):
        return struct.pack('<I', len(value)) + value.encode('utf-16le')

    def record(kind, data=b''):
        length = len(data)
        encoded_length = bytearray()
        while length >= 128:
            encoded_length.append((length & 127) | 128)
            length >>= 7
        encoded_length.append(length)
        return kind.to_bytes(2 if kind > 255 else 1, 'little') + encoded_length + data

    names = ['인적사항등록', '상담대장']
    tables = [PERSON_HEADERS, LOG_HEADERS]
    workbook = record(biff12.SHEETS)
    for index, name in enumerate(names, 1):
        workbook += record(biff12.SHEET, struct.pack('<II', 0, index) + string(f'rId{index}') + string(name))
    workbook += record(biff12.SHEETS_END)
    shared = list(dict.fromkeys(PERSON_HEADERS + LOG_HEADERS + ['SYNTHETIC_PERSON']))
    strings = record(biff12.SST, struct.pack('<II', len(shared), len(shared)))
    strings += b''.join(record(biff12.SI, b'\x00' + string(value)) for value in shared)
    strings += record(biff12.SST_END)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('xl/workbook.bin', workbook)
        archive.writestr('xl/sharedStrings.bin', strings)
        archive.writestr('xl/_rels/workbook.bin.rels', '<Relationships>' + ''.join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.bin"/>' for i in (1, 2)) + '</Relationships>')
        for index, headers in enumerate(tables, 1):
            sheet = record(biff12.DIMENSION, struct.pack('<IIII', 0, 1, 0, len(headers)-1))
            sheet += record(biff12.SHEETDATA) + record(biff12.ROW, struct.pack('<I', 0))
            for column, label in enumerate(headers):
                sheet += record(biff12.STRING, struct.pack('<III', column, 0, shared.index(label)))
            if index == 1:
                sheet += record(biff12.ROW, struct.pack('<I', 1))
                sheet += record(biff12.STRING, struct.pack('<III', headers.index('성명/집단명'), 0,
                                                          shared.index('SYNTHETIC_PERSON')))
            sheet += record(biff12.SHEETDATA_END)
            archive.writestr(f'xl/worksheets/sheet{index}.bin', sheet)
    with patch('pyxlsb.workbook.TemporaryFile', side_effect=AssertionError('disk file forbidden')):
        rows = read_rows(output.getvalue())
    assert rows['인적사항등록'][0][1]['성명/집단명'] == 'SYNTHETIC_PERSON'
    assert rows['상담대장'] == []


def test_existing_schema_upgrades_without_losing_legacy_widgets(tmp_path):
    db = database(tmp_path / 'old-schema.db')
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE home_widget_state')
        connection.execute("INSERT INTO home_todos (title) VALUES ('LEGACY_PRIVATE_TODO')")
    db.initialize()
    repo = HomeRepository(db)
    assert repo.todos()[0]['title'] == 'LEGACY_PRIVATE_TODO'
    assert not (tmp_path / 'display-settings.json').exists()
    db.initialize()
    assert len(HomeRepository(db).todos()) == 1
