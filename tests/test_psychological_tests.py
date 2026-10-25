"""심리검사 일지의 학생별 격리와 화면 선택 검증."""
import asyncio
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import StudentInput, PsychologicalTestInput
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.views.psychological_test_view import PsychologicalTestView


def test_storage_and_reinitialize(tmp_path):
    db = Database('test-only', tmp_path / 'tests.db')
    db.initialize()
    students = StudentRepository(db)
    first = students.create(StudentInput(name='첫 학생', grade=1, classroom='1'))
    second = students.create(StudentInput(name='다른 학생', grade=2, classroom='2'))
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
            with patch('maeumnarae.views.psychological_test_view.ui.timer'):
                view.build()
            view.repository = Mock()
            view.repository.list.return_value = []
            view.repository.count.return_value = 0
            started, release = asyncio.Event(), asyncio.Event()

            async def invoke(function, *args, **kwargs):
                if function is students.get and args == (1,):
                    started.set()
                    await release.wait()
                return function(*args, **kwargs)

            with patch('maeumnarae.views.psychological_test_view.run.io_bound', side_effect=invoke):
                assert not view.add.enabled
                pending = asyncio.create_task(view.select_student(1))
                await started.wait()
                await view.select_student(2)
                release.set()
                await pending
                assert view.selected.id == 2
                view.repository.list.assert_called_once_with(2, limit=10, offset=0)
                assert view.add.enabled
                assert view.message.text == '등록된 심리검사 일지가 없습니다.'
                await view.select_student(None)
                assert view.selected is None
                assert not view.add.enabled
                assert not view.logs.default_slot.children
    asyncio.run(check())


def test_editor_fields_storage_and_legacy_reinitialize(tmp_path):
    db = Database('test-only', tmp_path / 'legacy-tests.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    repo = PsychologicalTestRepository(db)
    saved = repo.save(PsychologicalTestInput(student_id=student.id, title='직접 입력한 검사', test_date='2026-10-20'))
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
            with patch('maeumnarae.views.psychological_test_view.ui.timer'):
                view.build(embedded=True)
            view.selected = student

            async def inspect_editor():
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
                assert fields['대상'].options == {'학생': '학생', '보호자(학부모)': '학부모'}
                assert fields['대상'].value == '보호자(학부모)'
                assert isinstance(fields['시각'], ui.time_input)
                assert fields['시각'].value == '오후 02:30'
                assert fields['시간(분)'].value == 45
                assert fields['검사일 *'].parent_slot is fields['시각'].parent_slot
                assert fields['시각'].parent_slot is fields['시간(분)'].parent_slot
                return False

            await view.open_editor(updated)
            await inspect_editor()
            assert not any(isinstance(element, ui.dialog) for element in ui.context.client.elements.values())
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


def test_inline_editor_save_retry_and_student_switch(tmp_path):
    from maeumnarae.core.database import DatabaseError

    async def check():
        db = Database('test-only', tmp_path / 'inline.db')
        db.initialize()
        students = StudentRepository(db)
        student = students.create(StudentInput(name='학생', grade=1, classroom='1'))
        with Client(page('/psychological-inline-save')) as client:
            view = PsychologicalTestView(students)
            with patch('maeumnarae.views.psychological_test_view.ui.timer'):
                view.build(embedded=True)

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch('maeumnarae.views.psychological_test_view.run.io_bound', side_effect=invoke):
                await view.select_student(student.id)
                await view.open_editor()
                elements = list(client.elements.values())
                title = next(e for e in elements if isinstance(e, ui.select) and e.label == '검사명 *')
                content = next(e for e in elements if isinstance(e, ui.editor))
                title.value = 'MBTI'
                content.value = '<p>검사 소견</p>'
                assert view.editor_open
                save = next(e for e in elements if isinstance(e, ui.button) and e.text == '일지 저장')
                from inspect import getclosurevars
                listener = next(e.handler for e in save._event_listeners.values() if e.type == 'click')
                handler = getclosurevars(listener).nonlocals['callback']
                with patch.object(view.repository, 'save', side_effect=DatabaseError('저장 실패')):
                    await handler()
                assert content.value == '<p>검사 소견</p>'
                assert view.editor_open and save.enabled
                await handler()
                assert len(view.repository.list(student.id)) == 1
                assert not view.editor_open
                content.value = '<p>수정 소견</p>'
                await handler()
                records = view.repository.list(student.id)
                assert len(records) == 1
                assert records[0].content == '<p>수정 소견</p>'
                content.value = '<p>미저장</p>'

                async def reject(dialog):
                    return False

                with patch.object(ui.dialog, '__await__', lambda dialog: reject(dialog).__await__()):
                    await view.select_student(None)
                assert view.selected.id == student.id
                assert content.value == '<p>미저장</p>'
                content.value = '<p>수정 소견</p>'
                await view.select_student(None)
                assert view.selected is None
                assert not view.editor_open
                assert not any(isinstance(e, ui.editor) for e in client.elements.values())
                await view.select_student(student.id)
                card = view.logs.default_slot.children[0]
                buttons = [e for e in card.descendants() if isinstance(e, ui.button)]
                assert len(buttons) == 1
                assert buttons[0]._props['icon'] == 'delete_outline'
                assert not buttons[0].text
                click = next(e for e in card._event_listeners.values() if e.type == 'click')
                await click.handler()
                assert any(isinstance(e, ui.editor) for e in view.editor_container.descendants())
    asyncio.run(check())
