"""Calendar drag moves preserve event data and reject stale/non-custom targets."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from maeumnarae.core.database import Database, DatabaseError, NotFoundError
from maeumnarae.core.models import CalendarInput, CalendarEventInput
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.services.reporting import KST


class CalendarMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database('test-password', Path(self.temp.name) / 'calendar.db')
        self.db.initialize()
        self.repo = CalendarRepository(self.db)
        self.calendar = self.repo.create(CalendarInput(name='테스트'))

    def create_event(self, all_day=False):
        start = datetime(2026, 11, 2, 0 if all_day else 9, tzinfo=KST)
        self.repo.save_event(CalendarEventInput(
            calendar_id=self.calendar.id, title='일정', starts_at=start,
            duration_minutes=4320 if all_day else 90, all_day=all_day,
            location='상담실', content='유지할 내용'))
        with self.db.session() as connection:
            return dict(connection.execute('SELECT * FROM calendar_events ORDER BY id DESC LIMIT 1').fetchone())

    def read_event(self, entry_id):
        with self.db.session() as connection:
            return dict(connection.execute('SELECT * FROM calendar_events WHERE id=?', (entry_id,)).fetchone())

    def test_moves_preserve_time_duration_and_other_fields(self):
        for all_day, delta in [(False, 30), (True, -3)]:
            with self.subTest(all_day=all_day):
                before = self.create_event(all_day)
                start = datetime.fromisoformat(before['starts_at'])
                self.repo.move_event(before['id'], start, delta)
                after = self.read_event(before['id'])
                self.assertEqual(datetime.fromisoformat(after['starts_at']), start + timedelta(days=delta))
                for key in before.keys() - {'starts_at', 'updated_at'}:
                    self.assertEqual(after[key], before[key], key)

    def test_stale_drag_does_not_overwrite_new_date(self):
        before = self.create_event()
        start = datetime.fromisoformat(before['starts_at'])
        self.repo.move_event(before['id'], start, 1)
        with self.assertRaises(DatabaseError):
            self.repo.move_event(before['id'], start, 2)
        self.assertEqual(datetime.fromisoformat(self.read_event(before['id'])['starts_at']), start + timedelta(days=1))

    def test_non_custom_calendar_is_not_movable(self):
        before = self.create_event()
        with self.db.session(write=True) as connection:
            connection.execute("UPDATE calendar_events SET calendar_id=(SELECT id FROM calendars WHERE source='counseling') WHERE id=?",
                               (before['id'],))
        with self.assertRaises(NotFoundError):
            self.repo.move_event(before['id'], datetime.fromisoformat(before['starts_at']), 1)
