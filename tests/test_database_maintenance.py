"""실제 SQLCipher 파일의 백업·검증·원자적 복원과 실패 시 원본 보존."""

from pathlib import Path
from unittest.mock import patch

import pytest

from maeumnarae.core.database import Database, DatabaseError, DatabaseOpenError, SCHEMA_VERSION
from maeumnarae.core.models import SchoolSettings, StudentInput
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.services.database_maintenance import create_backup, database_info, restore_backup


def make_database(path, password='original-key', name='Original'):
    database = Database(password, path)
    database.initialize(SchoolSettings(school_name=name))
    StudentRepository(database).create(StudentInput(name=name, grade=1, classroom='1'))
    return database


def student_names(database):
    return [student.name for student in StudentRepository(database).list()]


def test_backup_is_encrypted_complete_and_does_not_change_original(tmp_path):
    database = make_database(tmp_path / 'current.db')
    content = create_backup(database)
    assert content[:16] != b'SQLite format 3\x00'
    path = tmp_path / 'backup.db'
    path.write_bytes(content)
    backup = Database('original-key', path)
    assert student_names(backup) == ['Original']
    assert student_names(database) == ['Original']
    with pytest.raises(DatabaseOpenError):
        student_names(Database('wrong', path))
    info = database_info(database)
    assert info['students'] == 1
    assert info['schema_version'] == SCHEMA_VERSION
    assert info['size'] == database.path.stat().st_size
    assert Path(info['path']) == database.path.resolve()


def test_wal_backup_includes_committed_pages(tmp_path):
    database = make_database(tmp_path / 'wal.db')
    connection = database._connect()
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('SELECT * FROM students').fetchall()
        StudentRepository(database).create(StudentInput(name='WAL student', grade=2, classroom='2'))
        assert Path(str(database.path) + '-wal').stat().st_size > 0
        content = create_backup(database)
    finally:
        connection.close()
    path = tmp_path / 'wal-backup.db'
    path.write_bytes(content)
    assert set(student_names(Database('original-key', path))) == {'Original', 'WAL student'}


def test_restore_creates_recovery_and_invalidates_all_open_handles(tmp_path):
    current = make_database(tmp_path / 'current.db')
    other_handle = Database('original-key', current.path)
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    recovery = restore_backup(current, create_backup(source), 'backup-key')
    assert recovery.parent == tmp_path / 'backups'
    assert student_names(Database('original-key', recovery)) == ['Original']
    assert student_names(Database('backup-key', current.path)) == ['Restored']
    for handle in (current, other_handle):
        with pytest.raises(DatabaseOpenError):
            student_names(handle)
    with pytest.raises(DatabaseOpenError):
        student_names(Database('original-key', current.path))


@pytest.mark.parametrize('kind', ['wrong-password', 'corrupt', 'empty', 'future', 'unrelated', 'foreign-key'])
def test_invalid_restore_preserves_current_data(tmp_path, kind):
    current = make_database(tmp_path / 'current.db')
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    if kind == 'future':
        with source.session(write=True) as connection:
            connection.execute('PRAGMA user_version=99')
    if kind == 'unrelated':
        with source.session(write=True) as connection:
            connection.execute('PRAGMA user_version=0')
    if kind == 'foreign-key':
        connection = source._connect()
        try:
            connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute('INSERT INTO group_counseling_members (group_id, student_id) VALUES (999, 999)')
        finally:
            connection.close()
    content = source.path.read_bytes()
    password = 'wrong' if kind == 'wrong-password' else 'backup-key'
    if kind == 'corrupt':
        content = b'not a database'
    if kind == 'empty':
        content = b''
    with pytest.raises(DatabaseError):
        restore_backup(current, content, password)
    assert student_names(current) == ['Original']
    assert not (tmp_path / 'backups').exists()
    assert not list(tmp_path.glob('.restore-*'))


def test_replace_failure_preserves_current_and_recovery(tmp_path):
    current = make_database(tmp_path / 'current.db')
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    with patch('maeumnarae.services.database_maintenance.os.replace', side_effect=OSError('busy')):
        with pytest.raises(DatabaseError):
            restore_backup(current, create_backup(source), 'backup-key')
    assert student_names(current) == ['Original']
    recovery, = (tmp_path / 'backups').glob('*.db')
    assert student_names(Database('original-key', recovery)) == ['Original']


def test_auto_backup_failure_prevents_replacement(tmp_path):
    current = make_database(tmp_path / 'current.db')
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    (tmp_path / 'backups').write_text('not a directory')
    with pytest.raises(DatabaseError):
        restore_backup(current, create_backup(source), 'backup-key')
    assert student_names(current) == ['Original']


def test_restore_rejects_pre_release_schema_without_changing_files(tmp_path):
    current = make_database(tmp_path / 'current.db')
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    with source.session(write=True) as connection:
        connection.execute('PRAGMA user_version=38')
    before = current.path.read_bytes()
    source_before = source.path.read_bytes()
    with pytest.raises(DatabaseError, match='지원'):
        restore_backup(current, source_before, 'backup-key')
    assert current.path.read_bytes() == before
    assert source.path.read_bytes() == source_before


def test_locked_database_rejects_backup_and_restore(tmp_path):
    current = make_database(tmp_path / 'current.db')
    source = make_database(tmp_path / 'source.db', 'backup-key', 'Restored')
    content = create_backup(source)
    current.lock()
    with pytest.raises(DatabaseOpenError):
        create_backup(current)
    with pytest.raises(DatabaseOpenError):
        restore_backup(current, content, 'backup-key')
    assert student_names(Database('original-key', current.path)) == ['Original']
