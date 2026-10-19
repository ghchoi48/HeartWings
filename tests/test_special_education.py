"""특별교육 등록 항목과 학생/교육별 저장 격리 검증."""

import inspect
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database, ConflictError
from models import StudentInput, SpecialEducationInput, SpecialEducation, CounselingInput, Student
from repositories.student_repo import StudentRepository
from repositories.case_repo import CaseRepository
from repositories.counseling_repo import CounselingRepository
from repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from views.special_education_view import SpecialEducationView


def test_special_education_storage_and_migration(tmp_path):
    db = Database('test-only', tmp_path / 'special.db')
    db.initialize()
    students = StudentRepository(db)
    student = students.create(StudentInput(name='학생', grade=1, classroom='1'))
    other = students.create(StudentInput(name='다른 학생', grade=1, classroom='1'))
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE special_education_logs')
        connection.execute('DROP TABLE special_educations')
        connection.execute('DROP TABLE IF EXISTS education_events')
        connection.execute('ALTER TABLE consultations DROP COLUMN consultation_area')
        connection.execute('PRAGMA user_version=12')
    db.initialize()
    db.initialize()
    cases = SpecialEducationRepository(db)
    value = SpecialEducationInput(student_id=student.id, title='특별교육', law='학교폭력예방법', case_number='001')
    case = cases.save(value)
    second = cases.save(value.model_copy(update={'title': '두 번째 교육'}))
    assert cases.list(other.id) == []
    assert cases.list(student.id) == [second, case]
    case = cases.save(value.model_copy(update={'law': '교원지위법'}), case.id)
    assert case.law == '교원지위법'
    logs = SpecialEducationLogRepository(db)
    entry = CounselingInput(student_id=student.id, case_id=case.id, title='교육',
                            starts_at=datetime.now(timezone.utc), content_format='html', content_markdown='<b>내용</b>')
    saved = logs.create(entry)
    assert logs.get(saved.id) == saved
    assert logs.list(student_id=student.id, case_id=case.id) == [saved]
    assert logs.list(student_id=student.id, case_id=second.id) == []
    with pytest.raises(ConflictError):
        logs.create(entry.model_copy(update={'student_id': other.id}))
    updated = logs.update(saved.id, entry.model_copy(update={'follow_up': '후속'}))
    assert updated.follow_up == '후속'
    assert updated.created_at == saved.created_at
    assert CaseRepository(db).list(student.id) == []
    assert CounselingRepository(db).list(student_id=student.id) == []
    counseling = CounselingRepository(db)
    timeline = counseling.list_timeline(student_id=student.id)
    assert len(timeline) == 1
    assert timeline[0].kind == 'special_education'
    assert timeline[0].education_name == case.title
    assert counseling.list_timeline(student_id=other.id) == []
    personal = counseling.create(entry.model_copy(update={'case_id': None}))
    assert [item.kind for item in counseling.list_timeline(student_id=student.id)] == ['individual', 'special_education']
    assert counseling.list_timeline(student_id=student.id, limit=1)[0].id == personal.id
    assert counseling.list_timeline(student_id=student.id, limit=1, offset=1)[0].kind == 'special_education'


@pytest.mark.anyio
async def test_special_editor_fields_and_save():
    with Client(page('/special-editor-test')):
        now = datetime.now(timezone.utc)
        students = Mock()
        view = SpecialEducationView(students)
        with patch('views.special_education_view.ui.timer'):
            view.build()
        view.selected = Student(id=1, name='학생', grade=1, classroom='1', created_at=now, updated_at=now)
        view.cases = Mock()
        view.load_cases = AsyncMock()
        labels = [element.text for element in view.student_heading.client.content.descendants()
                  if isinstance(element, (ui.label, ui.button))]
        assert '특별 교육 목록' in labels
        assert '새 특별 교육' in labels
        assert '특별 교육 일지 목록' in labels
        assert '사례 개념화 보고서' not in labels
        assert '종결 보고서' not in labels

        async def interact(dialog):
            elements = list(dialog.descendants())
            fields = {element.label: element for element in elements if isinstance(element, (ui.input, ui.select))}
            assert set(fields) == {'특별교육명', '관련 법령', '사례번호'}
            assert fields['관련 법령'].options == ['학교폭력예방법', '교원지위법']
            fields['특별교육명'].value = '교육명'
            fields['관련 법령'].value = '교원지위법'
            fields['사례번호'].value = '001'
            button = next(element for element in elements if isinstance(element, ui.button) and element.text == '특별 교육 저장')
            handler = next(listener.handler for listener in button._event_listeners.values() if listener.type == 'click')
            await inspect.getclosurevars(handler).nonlocals['callback']()
            value = view.cases.save.call_args.args[0]
            assert value == SpecialEducationInput(student_id=1, title='교육명', law='교원지위법', case_number='001')
            return None

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()), \
                patch('views.special_education_view.run.io_bound', side_effect=invoke):
            await view.open_case_editor()
        assert not view.editor_open


@pytest.mark.anyio
async def test_student_selection_and_log_editor():
    with Client(page('/special-selection-test')):
        now = datetime.now(timezone.utc)
        students = Mock()
        student = Student(id=1, name='학생', grade=1, classroom='1', created_at=now, updated_at=now)
        students.get.return_value = student
        view = SpecialEducationView(students)
        with patch('views.special_education_view.ui.timer'):
            view.build()
        view.cases = Mock()
        view.cases.list.return_value = [SpecialEducation(id=1, student_id=1, title='교육', law='학교폭력예방법',
                                                        created_at=now, updated_at=now)]
        view.counseling = Mock()
        view.counseling.list.return_value = []

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke):
            await view.select_student(1)
        assert view.add.enabled
        assert view.edit_case.enabled
        assert '등록된 특별 교육 일지가 없습니다' in view.log_message.text
        view.counseling.list.assert_called_once_with(student_id=1, case_id=1, limit=21, offset=0)
        dialog, fields, _, _, _ = view.build_editor(student, None)
        assert fields['category'].value == '특별교육'
        assert fields['starts_on'].label == '교육 날짜'
        dialog.delete()
        await view.select_student(None)
        assert not view.add.enabled
        assert not view.edit_case.enabled


def test_law_migration_preserves_cases_and_logs(tmp_path):
    db = Database('test-only', tmp_path / 'law-migration.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    cases = SpecialEducationRepository(db)
    case = cases.save(SpecialEducationInput(student_id=student.id, title='기존 교육',
                                            law='학교폭력예방법', case_number='001'))
    other = cases.save(SpecialEducationInput(student_id=student.id, title='교원 교육', law='교원지위법'))
    logs = SpecialEducationLogRepository(db)
    entry = logs.create(CounselingInput(student_id=student.id, case_id=case.id, title='기존 일지',
                                        starts_at=datetime.now(timezone.utc), content_markdown='보존할 내용'))
    with db.session(write=True) as connection:
        connection.execute('PRAGMA ignore_check_constraints=ON')
        connection.execute("UPDATE special_educations SET law='학교폭력특별법' WHERE id=?", (case.id,))
        connection.execute('PRAGMA ignore_check_constraints=OFF')
        connection.execute('PRAGMA user_version=16')
    db.initialize()
    db.initialize()
    assert cases.list(student.id) == [other, case]
    assert logs.get(entry.id) == entry
    cases.save(SpecialEducationInput(student_id=student.id, title='새 교육', law='학교폭력예방법'))
    with db.session() as connection:
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='special_educations'").fetchone()[0]
        assert '학교폭력예방법' in schema
        assert '학교폭력특별법' not in schema
    with pytest.raises(ConflictError):
        with db.session(write=True) as connection:
            connection.execute('DELETE FROM special_educations WHERE id=?', (case.id,))
