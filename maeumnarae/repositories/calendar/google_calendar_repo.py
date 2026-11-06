"""Encrypted Google ICS subscriptions; secret URLs never enter display models."""
import re
from urllib.parse import urlsplit

from maeumnarae.core.database import NotFoundError
from maeumnarae.core.models import Calendar, CalendarInput


def validate_url(value):
    value = value.strip()
    try:
        url = urlsplit(value)
        valid = (url.scheme == 'https' and url.netloc == 'calendar.google.com'
                 and not url.query and not url.fragment
                 and re.fullmatch(r'/calendar/ical/[^/\s]+/private-[a-zA-Z0-9]+/basic\.ics', url.path))
    except ValueError:
        valid = False
    if not valid or any(ord(c) < 33 for c in value):
        raise ValueError('구글 캘린더의 비공개 iCal HTTPS 주소를 입력해 주세요.')
    return value


class GoogleCalendarRepository:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.session() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM google_calendar_subscriptions ORDER BY id')]

    def get(self, subscription_id):
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM google_calendar_subscriptions WHERE id=?', (subscription_id,)).fetchone()
            return dict(row) if row else None

    def calendars(self):
        with self.database.session() as connection:
            rows = connection.execute('SELECT id, name, color, visible FROM google_calendar_subscriptions ORDER BY id')
            return [Calendar(id=-(r['id'] + 2), name=r['name'], color=r['color'],
                             source='google_ics', visible=bool(r['visible'])) for r in rows]

    def save(self, value: CalendarInput, url, ics, fetched_at, subscription_id=None):
        value = CalendarInput.model_validate(value.model_dump())
        url = validate_url(url)
        with self.database.session(write=True) as connection:
            duplicate = connection.execute('SELECT id FROM google_calendar_subscriptions WHERE url=?', (url,)).fetchone()
            if duplicate and duplicate['id'] != subscription_id:
                raise ValueError('이미 연결된 구글 캘린더 주소입니다.')
            args = (value.name, value.color, url, ics, fetched_at, fetched_at)
            if subscription_id is None:
                return connection.execute('''INSERT INTO google_calendar_subscriptions
                    (name, color, url, ics, checked_at, fetched_at) VALUES (?, ?, ?, ?, ?, ?)''', args).lastrowid
            cursor = connection.execute('''UPDATE google_calendar_subscriptions SET name=?, color=?, url=?,
                ics=?, checked_at=?, fetched_at=?, error='', revision=revision+1 WHERE id=?''', (*args, subscription_id))
            if not cursor.rowcount:
                raise NotFoundError('연결된 캘린더를 찾을 수 없습니다.')
            return subscription_id

    def delete(self, subscription_id):
        with self.database.session(write=True) as connection:
            connection.execute('DELETE FROM google_calendar_subscriptions WHERE id=?', (subscription_id,))

    def set_visible(self, subscription_id, visible):
        with self.database.session(write=True) as connection:
            connection.execute('UPDATE google_calendar_subscriptions SET visible=? WHERE id=?', (int(visible), subscription_id))

    def store_result(self, row, checked_at, ics=None, error=''):
        # Compare revision as well as URL: an edit away and back must invalidate old requests.
        with self.database.session(write=True) as connection:
            connection.execute('''UPDATE google_calendar_subscriptions SET checked_at=?, error=?,
                ics=CASE WHEN ? IS NULL THEN ics ELSE ? END,
                fetched_at=CASE WHEN ? IS NULL THEN fetched_at ELSE ? END
                WHERE id=? AND revision=? AND url=?''',
                (checked_at, error, ics, ics, ics, checked_at, row['id'], row['revision'], row['url']))
