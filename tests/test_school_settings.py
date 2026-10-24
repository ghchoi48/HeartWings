"""암호화 DB의 학교 정보 저장, 재초기화 및 설정 화면 검증."""

import pytest
import inspect
import unittest
from unittest.mock import Mock, patch
from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from maeumnarae.core.database import Database
from maeumnarae.core.models import SchoolSettings, StudentInput
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.school_settings_view import build_school_settings
from maeumnarae.core.database import DatabaseError


def test_school_settings_persist_and_reinitialize(tmp_path):
    path = tmp_path / 'school.db'
    db = Database('test-only', path)
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=6, classroom='1'))
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
        with Client(page('/school-settings-form-test')):
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


@pytest.mark.parametrize('level,name,expected', [
    ('Wee센터', '서울', '마음나래 · 서울 Wee센터'),
    ('Wee센터', '', '마음나래 · Wee센터'),
    ('중학교', '우리학교', '마음나래 · 우리학교 Wee클래스'),
    ('초등학교', '', '마음나래 · Wee클래스'),
])
def test_school_header_title(level, name, expected):
    assert SchoolSettings(school_level=level, school_name=name).header_title == expected


def test_wee_center_migrates_existing_settings_and_preserves_authors(tmp_path):
    from maeumnarae.core import database as database_module

    db = Database('wee-center-test', tmp_path / 'school.db')
    old_schema = tuple(sql.replace(", 'Wee센터'", '') for sql in database_module.SCHEMA)
    original = SchoolSettings(school_name='기존학교', counselor_name='최초교사',
                              office_number='02-123-4567', neis_office_code='H10',
                              neis_school_code='1234567', neis_api_key='test-key')
    with patch.object(database_module, 'SCHEMA', old_schema):
        db.initialize(original)
    repo = SchoolSettingsRepository(db)
    repo.save(original.model_copy(update={'counselor_name': '현재교사'}))
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    db.initialize()
    db.initialize()
    assert repo.get().model_dump() == original.model_dump() | {'counselor_name': '현재교사'}
    with db.session() as connection:
        assert connection.execute('SELECT author FROM school_settings').fetchone()[0] == '최초교사'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    center = repo.save(SchoolSettings(school_name='테스트센터', school_level='Wee센터', counselor_name='센터교사'))
    reopened = Database('wee-center-test', db.path)
    reopened.initialize()
    assert SchoolSettingsRepository(reopened).get() == center
    assert StudentRepository(reopened).get(student.id) == student
    # 테이블 보완 뒤에도 다른 테이블의 작성자 트리거가 정상 동작한다.
    new_student = StudentRepository(reopened).create(StudentInput(name='다음학생', grade=1, classroom='1'))
    assert new_student.author == '센터교사'


def test_wee_center_name_label_switches_and_restores_on_load():
    import asyncio

    async def inline(function, *args):
        return function(*args)

    async def check():
        repo = Mock()
        repo.get.return_value = SchoolSettings(school_level='Wee센터', school_name='테스트센터')
        repo.save.side_effect = lambda settings: settings
        changed = Mock()
        with Client(page('/center-settings')), patch('maeumnarae.views.school_settings_view.ui.timer') as timer:
            host = ui.column()
            with host:
                build_school_settings(repo, changed)
            fields = {e.label: e for e in host.descendants() if isinstance(e, (ui.input, ui.select))}
            level, name = fields['학교급'], fields['학교명']
            with patch('maeumnarae.views.school_settings_view.run.io_bound', side_effect=inline), \
                    patch('maeumnarae.views.school_settings_view.ui.notify'):
                await timer.call_args.args[1]()
                assert name.label == '센터명'
                assert name.value == '테스트센터'
                level.value = '중학교'
                assert name.label == '학교명'
                level.value = 'Wee센터'
                assert name.label == '센터명'
                button = next(e for e in host.descendants() if isinstance(e, ui.button) and e.text == '학교 정보 저장')
                handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                await inspect.getclosurevars(handler).nonlocals['callback']()
                assert changed.call_args.args[0].header_title == '마음나래 · 테스트센터 Wee센터'
                assert repo.save.call_args.args[0].school_level == 'Wee센터'
    asyncio.run(check())
