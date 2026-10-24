"""교육/행사 저장과 목록 선택 검증."""
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
import unittest

import pytest
from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import EducationEvent, EducationEventInput
from maeumnarae.repositories.education_event_repo import EducationEventRepository
from maeumnarae.views.education_event_view import EducationEventView


def test_storage_and_reinitialize(tmp_path):
    db = Database('test-only', tmp_path / 'events.db')
    db.initialize()
    db.initialize()
    repo = EducationEventRepository(db)
    value = EducationEventInput(title=' 생명존중 교육 ', event_date=date(2026, 10, 20), content='첫 줄\n둘째 줄', event_time='13:30', duration_minutes=90)
    saved = repo.save(value)
    assert repo.get(saved.id).title == '생명존중 교육'
    assert repo.get(saved.id).event_time == '13:30'
    assert repo.get(saved.id).duration_minutes == 90
    updated = repo.save(value.model_copy(update={'category': '행사', 'location': '강당', 'event_time': '14:15', 'duration_minutes': 120}), saved.id)
    assert updated.event_time == '14:15'
    assert updated.duration_minutes == 120
    assert updated.created_at == saved.created_at
    assert updated.content == '첫 줄\n둘째 줄'
    assert repo.list() == [updated]
    db.initialize()
    assert repo.get(saved.id) == updated
    with pytest.raises(NotFoundError):
        repo.save(value, 999)
    with pytest.raises(ValidationError):
        EducationEventInput(title=' ', event_date='2026-02-30')


def test_participant_count_reinitialize_and_round_trip(tmp_path):
    db = Database('test-only', tmp_path / 'participants.db')
    db.initialize()
    repo = EducationEventRepository(db)
    value = EducationEventInput(title='행사', event_date='2026-10-23')
    saved = repo.save(value)
    db.initialize()
    db.initialize()
    assert repo.get(saved.id) == saved
    for count in (135, 0, None):
        updated = repo.save(value.model_copy(update={'participant_count': count}), saved.id)
        assert updated.participant_count == count
        assert updated.created_at == saved.created_at
        assert repo.get(saved.id) == updated
    created = repo.save(value.model_copy(update={'participant_count': 27}))
    assert repo.get(created.id).participant_count == 27
    for count in (-1, 1.5, 2147483648):
        with pytest.raises(ValidationError):
            EducationEventInput(title='행사', event_date='2026-10-23', participant_count=count)


class EducationEventViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_search_and_missing_record(self):
        with Client(page('/education-events-test')):
            now = datetime.now(timezone.utc)
            entry = EducationEvent(id=1, title='교육', event_date=date(2026, 10, 20),
                                   content='상세 내용', created_at=now, updated_at=now)
            repo = Mock()
            repo.list.return_value = [entry]
            repo.get.return_value = entry
            host = ui.column()
            view = EducationEventView(repo)

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            try:
                with host, patch('maeumnarae.views.education_event_view.ui.timer'):
                    view.build()
                with patch('maeumnarae.views.education_event_view.run.io_bound', side_effect=invoke):
                    await view.reload()
                    view.table.filter = '교육'
                    await view.select_event(1)
                    self.assertEqual(view.selected, entry)
                    self.assertEqual(view.table.selected[0]['id'], 1)
                    self.assertEqual(view.editor_fields['title'].value, entry.title)
                    await view.reload()
                    self.assertEqual(view.table.filter, '교육')
                    repo.get.return_value = None
                    await view.select_event(999)
                    self.assertIsNone(view.selected)
                    self.assertEqual(view.editor_fields, {})
                    self.assertEqual(view.table.selected, [])
            finally:
                host.delete()


def test_reinitialize_preserves_events(tmp_path):
    db = Database('test-only', tmp_path / 'legacy-events.db')
    db.initialize()
    repo = EducationEventRepository(db)
    saved = repo.save(EducationEventInput(title='기존 행사', event_date='2026-10-20'))
    db.initialize()
    db.initialize()
    restored = repo.get(saved.id)
    assert restored.title == '기존 행사'
    assert restored.event_time == ''
    assert restored.duration_minutes is None


@pytest.mark.parametrize('changes', [
    {'event_time': '24:00'}, {'event_time': '09:60'},
    {'duration_minutes': 0}, {'duration_minutes': 1441}, {'duration_minutes': 1.5},
])
def test_invalid_time_and_duration(changes):
    with pytest.raises(ValidationError):
        EducationEventInput(title='교육', event_date='2026-10-20', **changes)


def test_editor_restores_time_and_duration():
    with Client(page('/education-event-editor-test')):
        now = datetime.now(timezone.utc)
        entry = EducationEvent(id=1, title='행사', category='단체심리검사', event_date='2026-10-20',
                               event_time='15:30', duration_minutes=75, participant_count=120,
                               created_at=now, updated_at=now)
        view = EducationEventView(Mock())
        with patch('maeumnarae.views.education_event_view.ui.timer'):
            view.build()
        view.build_editor(entry)
        elements = list(ui.context.client.elements.values())
        fields = {element.label: element for element in elements
                  if isinstance(element, (ui.input, ui.number, ui.time_input, ui.select))}
        assert fields['구분'].options == ['교육', '행사', '단체심리검사']
        assert fields['구분'].value == '단체심리검사'
        assert fields['시각'].value == '오후 03:30'
        assert fields['운영 시간(분)'].value == 75
        assert fields['참여인원(명)'].value == 120
        assert fields['시각'].parent_slot is fields['운영 시간(분)'].parent_slot


def test_group_test_category_reinitialize_and_storage(tmp_path):
    db = Database('test-only', tmp_path / 'category.db')
    db.initialize()
    repo = EducationEventRepository(db)
    value = EducationEventInput(title='기존 교육', event_date='2026-10-20',
                                event_time='10:30', duration_minutes=45, content='내용')
    saved = repo.save(value)
    db.initialize()
    db.initialize()
    assert repo.get(saved.id) == saved
    updated = repo.save(value.model_copy(update={'category': '단체심리검사'}), saved.id)
    assert updated.category == '단체심리검사'
    created = repo.save(value.model_copy(update={'category': '단체심리검사'}))
    assert repo.get(created.id) == created
    assert repo.list() == [created, updated]


def test_inline_save_retry_switch_and_close(tmp_path):
    import asyncio
    from inspect import getclosurevars
    from maeumnarae.core.database import DatabaseError

    async def check():
        db = Database('test-only', tmp_path / 'inline.db')
        db.initialize()
        repo = EducationEventRepository(db)
        with Client(page('/education-inline')) as client:
            view = EducationEventView(repo)
            with patch('maeumnarae.views.education_event_view.ui.timer'):
                view.build()

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch('maeumnarae.views.education_event_view.run.io_bound', side_effect=invoke):
                await view.open_editor()
                assert not any(isinstance(e, ui.dialog) for e in client.elements.values())
                title = view.editor_fields['title']
                title.value = '새 교육'
                save = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text == '저장')
                listener = next(e.handler for e in save._event_listeners.values() if e.type == 'click')
                handler = getclosurevars(listener).nonlocals['callback']
                with patch.object(repo, 'save', side_effect=DatabaseError('저장 실패')):
                    await handler()
                assert view.editor_open and title.value == '새 교육' and save.enabled
                await handler()
                assert len(repo.list()) == 1
                assert not view.editor_open
                title.value = '수정 교육'
                await handler()
                assert len(repo.list()) == 1
                assert repo.list()[0].title == '수정 교육'
                title.value = '미저장'

                async def reject(dialog):
                    return False

                with patch.object(ui.dialog, '__await__', lambda dialog: reject(dialog).__await__()):
                    await view.open_editor()
                    await view.select_event(None)
                assert view.editor_fields['title'] is title
                assert title.value == '미저장'
                title.value = '수정 교육'
                await view.select_event(None)
                assert view.selected is None and not view.editor_fields
                await view.select_event(repo.list()[0].id)
                assert view.editor_fields['title'].value == '수정 교육'
                assert not view.editor_open
    asyncio.run(check())


def test_row_delete_targets_clicked_record_and_keeps_other_editor(tmp_path):
    import asyncio
    from types import SimpleNamespace

    async def check():
        db = Database('test-only', tmp_path / 'row-delete.db')
        db.initialize()
        repo = EducationEventRepository(db)
        first = repo.save(EducationEventInput(title='첫 교육', event_date='2026-10-20'))
        second = repo.save(EducationEventInput(title='둘째 교육', event_date='2026-10-21'))
        with Client(page('/education-row-delete')), patch('maeumnarae.views.education_event_view.ui.timer'):
            view = EducationEventView(repo)
            view.build()
            assert view.table.props.get('selection') in (None, 'none')
            assert view.table.columns[-1]['name'] == 'actions'

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            async def confirm(dialog):
                return True

            async def cancel(dialog):
                return False

            with patch('maeumnarae.views.education_event_view.run.io_bound', side_effect=invoke):
                await view.reload()
                await view.select_event(first.id)
                with patch.object(ui.dialog, '__await__', lambda dialog: cancel(dialog).__await__()):
                    await view.delete_event(SimpleNamespace(args=second.id))
                assert repo.get(second.id) is not None
                view.editor_fields['title'].value = '저장 전'
                await view.delete_event(SimpleNamespace(args=second.id))
                assert repo.get(second.id) is not None
                view.editor_fields['title'].value = first.title
                with patch.object(ui.dialog, '__await__', lambda dialog: confirm(dialog).__await__()):
                    await view.delete_event(SimpleNamespace(args=second.id))
                    assert repo.get(second.id) is None
                    assert view.selected.id == first.id
                    assert view.editor_fields['title'].value == first.title
                    await view.delete_event(SimpleNamespace(args=first.id))
                assert repo.list() == []
                assert view.selected is None and not view.editor_fields
                assert not view.deleting
    asyncio.run(check())
