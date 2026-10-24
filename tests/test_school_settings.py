"""암호화 DB의 학교 정보 저장, 복원 및 이전 버전 업그레이드."""

import pytest
import inspect
import unittest
from unittest.mock import Mock, patch
from nicegui import ui
from pydantic import ValidationError

from maeumnarae.core.database import Database
from maeumnarae.core.models import SchoolSettings, StudentInput
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.school_settings_view import build_school_settings
from maeumnarae.core.database import DatabaseError


def test_school_settings_persist_and_migrate(tmp_path):
    path = tmp_path / 'school.db'
    db = Database('test-only', path)
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=6, classroom='1'))
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE school_settings')
        connection.execute('PRAGMA user_version=23')
    db.initialize()
    repo = SchoolSettingsRepository(db)
    assert repo.get() == SchoolSettings()
    saved = repo.save(SchoolSettings(school_name=' 우리학교 ', school_level='초등학교',
                                    counselor_name=' 상담교사 ', office_number='02-0123-0045'))
    assert saved.school_name == '우리학교'
    db.lock()
    reopened = Database('test-only', path)
    reopened.initialize()
    assert SchoolSettingsRepository(reopened).get() == saved
    SchoolSettingsRepository(reopened).save(SchoolSettings(school_level='고등학교'))
    assert StudentRepository(reopened).get(student.id).grade == 6


@pytest.mark.parametrize('level,count', [('초등학교', 6), ('중학교', 3), ('고등학교', 3)])
def test_grade_options(level, count):
    assert list(SchoolSettings(school_level=level).grade_options) == list(range(1, count + 1))


def test_invalid_school_level():
    with pytest.raises(ValidationError):
        SchoolSettings(school_level='대학교')


def test_initial_school_information_is_saved_only_for_new_database(tmp_path):
    db = Database('test-only', tmp_path / 'first-run.db')
    school = SchoolSettings(school_name='첫학교', school_level='초등학교',
                            counselor_name='김교사', office_number='02-001-002')
    db.initialize(school)
    assert SchoolSettingsRepository(db).get() == school
    db.initialize(SchoolSettings(school_name='덮어쓰면 안 되는 학교'))
    assert SchoolSettingsRepository(db).get() == school
    db.lock()
    reopened = Database('test-only', db.path)
    reopened.initialize()
    assert SchoolSettingsRepository(reopened).get() == school


class SchoolSettingsFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_save_failure_and_retry(self):
        async def inline_io(function, *args):
            return function(*args)

        repository = Mock()
        repository.get.return_value = SchoolSettings(school_name='기존학교')
        host = ui.column()
        try:
            with host, patch('maeumnarae.views.school_settings_view.ui.timer') as timer:
                build_school_settings(repository)
            fields = {e.props['label']: e for e in host.descendants() if isinstance(e, (ui.input, ui.select))}
            button = next(e for e in host.descendants() if isinstance(e, ui.button) and e.text == '학교 정보 저장')
            with host, patch('maeumnarae.views.school_settings_view.run.io_bound', side_effect=inline_io), \
                    patch('maeumnarae.views.school_settings_view.ui.notify'):
                await timer.call_args.args[1]()
                self.assertEqual(fields['학교명'].value, '기존학교')
                fields['학교명'].value = '새학교'
                fields['학교급'].value = '초등학교'
                fields['상담교사 이름'].value = '김교사'
                fields['사무실 번호'].value = '02-001-002'
                handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                save = inspect.getclosurevars(handler).nonlocals['callback']
                repository.save.side_effect = DatabaseError('저장 실패')
                await save()
                self.assertTrue(button.enabled)
                self.assertEqual(fields['학교명'].value, '새학교')
                repository.save.side_effect = lambda value: value
                await save()
                settings = repository.save.call_args.args[0]
                self.assertEqual(settings.school_level, '초등학교')
                self.assertEqual(settings.office_number, '02-001-002')
                self.assertEqual(settings.counselor_name, '김교사')
        finally:
            host.delete()
