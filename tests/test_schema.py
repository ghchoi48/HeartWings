"""최초 스키마 생성, 원자성, 재실행 및 지원하지 않는 DB 보존 검증."""

from unittest.mock import patch

import pytest

from maeumnarae.core import database as database_module
from maeumnarae.core.database import Database, DatabaseError, SCHEMA_VERSION
from maeumnarae.core.models import SchoolSettings, StudentInput
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.repositories.student_repo import StudentRepository


def test_fresh_database_has_current_structure_and_seed_authors(tmp_path):
    db = Database('schema-test', tmp_path / 'fresh.db')
    db.initialize(SchoolSettings(school_name='테스트학교', counselor_name='첫 교사'))
    with db.session() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION == 1
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == {
            'students', 'student_enrollments', 'counseling', 'counseling_cases',
            'counseling_groups', 'group_counseling_logs', 'group_counseling_members',
            'teachers', 'consultations', 'special_educations', 'special_education_logs',
            'psychological_tests', 'education_events', 'calendars', 'calendar_events',
            'calendar_preferences', 'school_settings', 'home_preferences', 'home_todos', 'home_widget_state',
            'journal_attachments',
        }
        for table in ('school_settings', 'calendars', 'calendar_preferences'):
            assert connection.execute(f'SELECT author FROM {table}').fetchone()[0] == '첫 교사'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    assert not db.path.read_bytes().startswith(b'SQLite format 3')


def test_reinitialize_preserves_school_students_and_seeds(tmp_path):
    db = Database('schema-test', tmp_path / 'repeat.db')
    school = SchoolSettings(school_name='테스트학교', counselor_name='첫 교사')
    db.initialize(school)
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    reopened = Database('schema-test', db.path)
    reopened.initialize(SchoolSettings(counselor_name='덮어쓰지 않음'))
    reopened.initialize()
    assert SchoolSettingsRepository(reopened).get() == school
    assert StudentRepository(reopened).get(student.id) == student
    with reopened.session() as connection:
        assert connection.execute('SELECT count(*) FROM calendars').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM calendar_preferences').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM student_enrollments').fetchone()[0] == 1


def test_failed_creation_rolls_back_schema_and_version(tmp_path):
    db = Database('schema-test', tmp_path / 'failure.db')
    with patch.object(database_module, 'SCHEMA', (*database_module.SCHEMA, 'INVALID SQL')):
        with pytest.raises(DatabaseError):
            db.initialize()
    with db.session() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 0
        assert not connection.execute('SELECT name FROM sqlite_master').fetchall()
    db.initialize()
    assert SchoolSettingsRepository(db).get() == SchoolSettings()


@pytest.mark.parametrize('version', [0, 2, 26, 38, 99])
def test_unsupported_database_is_preserved(tmp_path, version):
    db = Database('schema-test', tmp_path / 'unsupported.db')
    with db.session(write=True) as connection:
        connection.execute('CREATE TABLE existing (value TEXT)')
        connection.execute("INSERT INTO existing VALUES ('보존')")
        connection.execute(f'PRAGMA user_version={version}')
    before = db.path.read_bytes()
    with pytest.raises(DatabaseError, match='지원하지 않는'):
        db.initialize()
    assert db.path.read_bytes() == before
