"""교육/행사 저장과 목록 선택 검증."""
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
import unittest

import pytest
from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from database import Database, NotFoundError
from models import EducationEvent, EducationEventInput
from repositories.education_event_repo import EducationEventRepository
from views.education_event_view import EducationEventView


def test_storage_and_migration(tmp_path):
    db = Database('test-only', tmp_path / 'events.db')
    db.initialize()
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE education_events')
        connection.execute('ALTER TABLE consultations DROP COLUMN consultation_area')
        connection.execute('PRAGMA user_version=13')
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
                with host, patch('views.education_event_view.ui.timer'):
                    view.build()
                with patch('views.education_event_view.run.io_bound', side_effect=invoke):
                    await view.reload()
                    view.table.filter = '교육'
                    await view.select_event(1)
                    self.assertEqual(view.selected, entry)
                    self.assertEqual(view.table.selected[0]['id'], 1)
                    self.assertTrue(view.edit.enabled)
                    await view.reload()
                    self.assertEqual(view.table.filter, '교육')
                    repo.get.return_value = None
                    await view.select_event(999)
                    self.assertIsNone(view.selected)
                    self.assertFalse(view.edit.enabled)
                    self.assertEqual(view.table.selected, [])
            finally:
                host.delete()


def test_version_fourteen_preserves_events(tmp_path):
    db = Database('test-only', tmp_path / 'legacy-events.db')
    db.initialize()
    repo = EducationEventRepository(db)
    saved = repo.save(EducationEventInput(title='기존 행사', event_date='2026-10-20'))
    with db.session(write=True) as connection:
        connection.execute('ALTER TABLE education_events DROP COLUMN event_time')
        connection.execute('ALTER TABLE education_events DROP COLUMN duration_minutes')
        connection.execute('ALTER TABLE consultations DROP COLUMN consultation_area')
        connection.execute('PRAGMA user_version=14')
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
                               event_time='15:30', duration_minutes=75,
                               created_at=now, updated_at=now)
        view = EducationEventView(Mock())
        view.open_editor(entry)
        elements = list(ui.context.client.elements.values())
        fields = {element.label: element for element in elements
                  if isinstance(element, (ui.input, ui.number, ui.time_input, ui.select))}
        assert fields['구분'].options == ['교육', '행사', '단체심리검사']
        assert fields['구분'].value == '단체심리검사'
        assert fields['시각'].value == '15:30'
        assert fields['운영 시간(분)'].value == 75
        assert fields['시각'].parent_slot is fields['운영 시간(분)'].parent_slot


def test_group_test_category_migration_and_storage(tmp_path):
    db = Database('test-only', tmp_path / 'category.db')
    db.initialize()
    repo = EducationEventRepository(db)
    value = EducationEventInput(title='기존 교육', event_date='2026-10-20',
                                event_time='10:30', duration_minutes=45, content='내용')
    saved = repo.save(value)
    with db.session(write=True) as connection:
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='education_events'").fetchone()[0]
        legacy_schema = schema.replace('education_events', 'education_events_legacy').replace(
            "'교육', '행사', '단체심리검사'", "'교육', '행사'")
        connection.execute(legacy_schema)
        connection.execute('INSERT INTO education_events_legacy SELECT * FROM education_events')
        connection.execute('DROP TABLE education_events')
        connection.execute('ALTER TABLE education_events_legacy RENAME TO education_events')
        connection.execute('PRAGMA user_version=18')
    db.initialize()
    db.initialize()
    assert repo.get(saved.id) == saved
    updated = repo.save(value.model_copy(update={'category': '단체심리검사'}), saved.id)
    assert updated.category == '단체심리검사'
    created = repo.save(value.model_copy(update={'category': '단체심리검사'}))
    assert repo.get(created.id) == created
    assert repo.list() == [created, updated]
