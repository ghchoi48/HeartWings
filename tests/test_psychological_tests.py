"""심리검사 일지의 학생별 격리와 화면 선택 검증."""
import asyncio
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database, NotFoundError
from models import StudentInput, PsychologicalTestInput
from repositories.student_repo import StudentRepository
from repositories.psychological_test_repo import PsychologicalTestRepository
from views.psychological_test_view import PsychologicalTestView


def test_storage_and_migration(tmp_path):
    db = Database('test-only', tmp_path / 'tests.db')
    db.initialize()
    students = StudentRepository(db)
    first = students.create(StudentInput(name='첫 학생', grade=1, classroom='1'))
    second = students.create(StudentInput(name='다른 학생', grade=2, classroom='2'))
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE psychological_tests')
        connection.execute('PRAGMA user_version=17')
    db.initialize()
    repo = PsychologicalTestRepository(db)
    value = PsychologicalTestInput(student_id=first.id, title='성격 검사', test_date='2026-10-20', content='결과\n소견')
    saved = repo.save(value)
    newer = repo.save(value.model_copy(update={'title': '후속 검사'}))
    assert repo.list(first.id, limit=1) == [newer]
    assert repo.list(first.id, limit=1, offset=1) == [saved]
    assert repo.list(second.id) == []
    with pytest.raises(NotFoundError):
        repo.save(value.model_copy(update={'student_id': second.id}), saved.id)
    updated = repo.save(value.model_copy(update={'content': '수정한 소견'}), saved.id)
    assert updated.created_at == saved.created_at
    db.initialize()
    assert repo.list(first.id)[1].content == '수정한 소견'


def test_student_selection_and_stale_response():
    async def check():
        with Client(page('/psychological-tests-test')):
            students = Mock()
            students.get.side_effect = lambda student_id: Mock(id=student_id, name=f'학생 {student_id}', grade=1, classroom='1')
            view = PsychologicalTestView(students)
            with patch('views.psychological_test_view.ui.timer'):
                view.build()
            view.repository = Mock()
            view.repository.list.return_value = []
            started, release = asyncio.Event(), asyncio.Event()

            async def invoke(function, *args, **kwargs):
                if function is students.get and args == (1,):
                    started.set()
                    await release.wait()
                return function(*args, **kwargs)

            with patch('views.psychological_test_view.run.io_bound', side_effect=invoke):
                assert not view.add.enabled
                pending = asyncio.create_task(view.select_student(1))
                await started.wait()
                await view.select_student(2)
                release.set()
                await pending
                assert view.selected.id == 2
                view.repository.list.assert_called_once_with(2, limit=21, offset=0)
                assert view.add.enabled
                assert view.message.text == '등록된 심리검사 일지가 없습니다.'
                await view.select_student(None)
                assert view.selected is None
                assert not view.add.enabled
                assert not view.logs.default_slot.children
    asyncio.run(check())


def test_editor_fields_storage_and_legacy_migration(tmp_path):
    db = Database('test-only', tmp_path / 'legacy-tests.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    repo = PsychologicalTestRepository(db)
    saved = repo.save(PsychologicalTestInput(student_id=student.id, title='직접 입력한 검사', test_date='2026-10-20'))
    with db.session(write=True) as connection:
        for column in ('target', 'test_time', 'duration_minutes'):
            connection.execute(f'ALTER TABLE psychological_tests DROP COLUMN {column}')
        connection.execute('PRAGMA user_version=19')
    db.initialize()
    restored = repo.list(student.id)[0]
    assert restored.id == saved.id
    assert restored.target == '학생'
    assert restored.test_time == ''
    assert restored.duration_minutes is None
    value = PsychologicalTestInput(student_id=student.id, title='직접 입력한 검사', test_date='2026-10-20',
                                   target='보호자(학부모)', test_time='14:30', duration_minutes=45)
    updated = repo.save(value, saved.id)
    created = repo.save(value)
    db.initialize()
    assert repo.list(student.id) == [created, updated]
    assert updated.target == '보호자(학부모)'
    assert updated.test_time == '14:30'
    assert updated.duration_minutes == 45

    async def check():
        with Client(page('/psychological-test-editor-fields')):
            view = PsychologicalTestView(StudentRepository(db))
            view.selected = student

            async def inspect_dialog(dialog):
                elements = list(ui.context.client.elements.values())
                editors = [element for element in elements if isinstance(element, ui.editor)]
                assert len(editors) == 1
                fields = {element.label: element for element in elements
                          if isinstance(element, (ui.input, ui.select, ui.number, ui.date_input, ui.time_input))}
                assert fields['검사명 *'].value == '직접 입력한 검사'
                assert isinstance(fields['검사명 *'], ui.select)
                assert any('MMPI-A' in option for option in fields['검사명 *'].options)
                assert fields['검사명 *']._props['use-input']
                assert fields['검사명 *']._props['new-value-mode'] == 'add-unique'
                assert fields['대상'].options == ['학생', '보호자(학부모)']
                assert fields['대상'].value == '보호자(학부모)'
                assert isinstance(fields['시각'], ui.time_input)
                assert fields['시각'].value == '14:30'
                assert fields['시간(분)'].value == 45
                assert fields['검사일 *'].parent_slot is fields['시각'].parent_slot
                assert fields['시각'].parent_slot is fields['시간(분)'].parent_slot
                return False

            with patch.object(ui.dialog, '__await__', lambda dialog: inspect_dialog(dialog).__await__()):
                await view.open_editor(updated)
            assert not view.editor_open
    asyncio.run(check())


@pytest.mark.parametrize('changes', [
    {'target': '교사'}, {'test_time': '24:00'}, {'test_time': '09:60'},
    {'duration_minutes': 0}, {'duration_minutes': 1441}, {'duration_minutes': 1.5},
])
def test_invalid_editor_values(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PsychologicalTestInput(student_id=1, title='검사', test_date='2026-10-20', **changes)
