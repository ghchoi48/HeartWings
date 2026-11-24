"""Last successful school schedules, stored in the encrypted database by day."""
import json
from datetime import timedelta

from maeumnarae.core.models import CalendarEvent


class SchoolCalendarRepository:
    def __init__(self, database):
        self.database = database

    def get(self, office, school, start, end):
        with self.database.session() as connection:
            rows = connection.execute('''SELECT day, events, fetched_at FROM school_calendar_cache
                WHERE office_code=? AND school_code=? AND day BETWEEN ? AND ? ORDER BY day''',
                (office, school, start.isoformat(), end.isoformat())).fetchall()
        events = [CalendarEvent.model_validate(event) for row in rows for event in json.loads(row['events'])]
        # Empty days count as successfully fetched, too.
        checked = min((row['fetched_at'] for row in rows), default=None)
        if len(rows) != (end - start).days + 1:
            checked = None
        return events, checked

    def store(self, settings, start, end, events, fetched_at):
        by_day = {}
        for event in events:
            by_day.setdefault(event.starts_at.date().isoformat(), []).append(event.model_dump(mode='json'))
        with self.database.session(write=True) as connection:
            current = connection.execute('''SELECT neis_office_code, neis_school_code, neis_api_key
                FROM school_settings WHERE id=1''').fetchone()
            if not current or tuple(current) != (
                    settings.neis_office_code, settings.neis_school_code, settings.neis_api_key):
                return False
            for offset in range((end - start).days + 1):
                day = (start + timedelta(days=offset)).isoformat()
                connection.execute('''INSERT INTO school_calendar_cache
                    (office_code, school_code, day, events, fetched_at) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(office_code, school_code, day) DO UPDATE SET
                    events=excluded.events, fetched_at=excluded.fetched_at''',
                    (settings.neis_office_code, settings.neis_school_code, day,
                     json.dumps(by_day.get(day, []), ensure_ascii=False), fetched_at))
        return True
