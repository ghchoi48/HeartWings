"""캘린더 설정과 사용자 일정, 상담·자문·특별교육·교육/행사 일정의 통합 조회."""
from datetime import date, datetime, time, timedelta

from maeumnarae.core.database import Database, DatabaseError, NotFoundError
from maeumnarae.services.calendar_holidays import HOLIDAY_CALENDAR_ID, HOLIDAY_COLOR
from maeumnarae.core.models import Calendar, CalendarInput, CalendarEvent, CalendarEventInput
from maeumnarae.repositories._support import now_text, utc_text, values
from maeumnarae.services.reporting import KST
from maeumnarae.repositories.reporting_repo import ReportingRepository
from maeumnarae.services.school_calendar import NEIS_CALENDAR_ID, NEIS_COLOR, NEIS_NAME


class CalendarRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self) -> list[Calendar]:
        with self.database.session() as connection:
            calendars = [Calendar.model_validate(dict(row)) for row in connection.execute(
                "SELECT * FROM calendars ORDER BY CASE source WHEN 'counseling' THEN 0 ELSE 1 END, id")]
            calendars = [item.model_copy(update={'name': '상담 일정'}) if item.source == 'counseling' else item
                         for item in calendars]
            visible = connection.execute("SELECT visible FROM calendar_preferences WHERE name='holidays'").fetchone()['visible']
            neis = connection.execute("SELECT visible FROM calendar_preferences WHERE name='neis'").fetchone()
            return calendars + [Calendar(id=HOLIDAY_CALENDAR_ID, name='대한민국 공휴일', color=HOLIDAY_COLOR,
                                         source='holidays', visible=bool(visible)),
                                Calendar(id=NEIS_CALENDAR_ID, name=NEIS_NAME, color=NEIS_COLOR,
                                         source='neis', visible=bool(neis['visible']) if neis else False)]

    def create(self, value: CalendarInput) -> Calendar:
        data = values(CalendarInput.model_validate(value.model_dump()))
        with self.database.session(write=True) as connection:
            cursor = connection.execute("INSERT INTO calendars (name, color, source) VALUES (:name, :color, 'custom')", data)
            row = connection.execute('SELECT * FROM calendars WHERE id=?', (cursor.lastrowid,)).fetchone()
            return Calendar.model_validate(dict(row))

    def update(self, calendar_id: int, value: CalendarInput):
        data = values(CalendarInput.model_validate(value.model_dump()))
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                "UPDATE calendars SET name=:name, color=:color WHERE id=:id AND source='custom'",
                {**data, 'id': calendar_id})
            if not cursor.rowcount:
                raise NotFoundError('수정할 사용자 캘린더를 찾을 수 없습니다.')

    def delete(self, calendar_id: int):
        with self.database.session(write=True) as connection:
            target = connection.execute(
                "SELECT id FROM calendars WHERE id=? AND source='custom'", (calendar_id,)).fetchone()
            if target is None:
                raise NotFoundError('삭제할 사용자 캘린더를 찾을 수 없습니다.')
            connection.execute('DELETE FROM calendar_events WHERE calendar_id=?', (calendar_id,))
            connection.execute('DELETE FROM calendars WHERE id=?', (calendar_id,))

    def set_visible(self, calendar_id: int, visible: bool):
        with self.database.session(write=True) as connection:
            if calendar_id == NEIS_CALENDAR_ID:
                connection.execute("INSERT INTO calendar_preferences (name, visible) VALUES ('neis', ?) "
                                   "ON CONFLICT(name) DO UPDATE SET visible=excluded.visible", (int(visible),))
                return
            if calendar_id == HOLIDAY_CALENDAR_ID:
                connection.execute("UPDATE calendar_preferences SET visible=? WHERE name='holidays'", (int(visible),))
                return
            cursor = connection.execute('UPDATE calendars SET visible=? WHERE id=?', (int(visible), calendar_id))
            if not cursor.rowcount:
                raise NotFoundError('캘린더를 찾을 수 없습니다.')

    def events(self, start: date, end: date, calendar_ids: list[int], status=None) -> list[CalendarEvent]:
        params = ReportingRepository._params(start, end, status)
        if not calendar_ids:
            return []
        slots = ','.join(f':calendar_{i}' for i in range(len(calendar_ids)))
        params.update({f'calendar_{i}': value for i, value in enumerate(calendar_ids)})
        with self.database.session() as connection:
            rows = connection.execute(f'''SELECT e.id AS id, e.calendar_id AS calendar_id, e.title, e.starts_at,
                    e.duration_minutes, NULL AS status, c.source, c.name AS calendar_name, c.color,
                    '' AS student_name, e.author, '' AS display_name, NULL AS owner_id, e.location, e.content, e.all_day
                FROM calendar_events e JOIN calendars c ON c.id=e.calendar_id
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND :status IS NULL
                UNION ALL
                SELECT e.id, c.id AS calendar_id, e.title, e.starts_at,
                    e.duration_minutes, e.status, c.source, '상담 일정' AS calendar_name, c.color,
                    s.name AS student_name, e.author, s.name AS display_name, s.id AS owner_id, '' AS location, '' AS content, 0 AS all_day
                FROM counseling e JOIN students s ON s.id=e.student_id
                    JOIN calendars c ON c.source='counseling'
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND (:status IS NULL OR e.status=:status)
                UNION ALL
                SELECT e.id, c.id, e.title, e.starts_at, e.duration_minutes,
                    e.status, 'group' AS source, '상담 일정', c.color,
                    '', e.author, g.name, g.id, '', '', 0
                FROM group_counseling_logs e JOIN counseling_groups g ON g.id=e.group_id
                    JOIN calendars c ON c.source='counseling'
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND (:status IS NULL OR e.status=:status)
                UNION ALL
                SELECT e.id, c.id, e.title, e.starts_at, e.duration_minutes,
                    e.status, 'consultation' AS source, '상담 일정', c.color,
                    '', e.author, t.name, t.id, '', '', 0
                FROM consultations e JOIN teachers t ON t.id=e.teacher_id
                    JOIN calendars c ON c.source='counseling'
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND (:status IS NULL OR e.status=:status)
                UNION ALL
                SELECT e.id, c.id, e.title, e.starts_at, e.duration_minutes,
                    e.status, 'special_education' AS source, '상담 일정', c.color,
                    s.name, e.author, s.name, s.id, '', '', 0
                FROM special_education_logs e JOIN students s ON s.id=e.student_id
                    JOIN calendars c ON c.source='counseling'
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND (:status IS NULL OR e.status=:status)
                ORDER BY starts_at, calendar_id, source, id''', params).fetchall()
            events = [CalendarEvent.model_validate(dict(row)) for row in rows]
            if status is None:
                education_rows = connection.execute(f'''SELECT e.id, e.title, e.event_date, e.event_time,
                    e.duration_minutes, e.location, e.author, c.id AS calendar_id, c.color
                    FROM education_events e JOIN calendars c ON c.source='counseling'
                    WHERE c.id IN ({slots}) AND e.event_date BETWEEN :education_start AND :education_end''',
                    {**params, 'education_start': (start - timedelta(days=1)).isoformat(),
                     'education_end': end.isoformat()}).fetchall()
                for row in education_rows:
                    all_day = not row['event_time']
                    begins = datetime.combine(date.fromisoformat(row['event_date']),
                                              time.fromisoformat(row['event_time']) if not all_day else time.min, KST)
                    # A missing time is shown as an all-day entry; a missing duration
                    # uses the smallest interval so it does not imply an invented end time.
                    duration = 1440 if all_day else row['duration_minutes'] or 1
                    if begins >= datetime.fromisoformat(params['end']) or (
                            begins + timedelta(minutes=duration) <= datetime.fromisoformat(params['start'])):
                        continue
                    events.append(CalendarEvent(
                        id=row['id'], calendar_id=row['calendar_id'], title=row['title'],
                        starts_at=begins, duration_minutes=duration, all_day=all_day,
                        source='education_event', calendar_name='상담 일정', color=row['color'],
                        display_name=row['title'], location=row['location'], author=row['author']))
            return sorted(events, key=lambda e: (e.starts_at, e.calendar_id, e.source, e.id))

    def move_event(self, entry_id: int, expected_start: datetime, days: int):
        """사용자 일정의 시작 시각만 이동하며 동시 변경된 일정은 덮어쓰지 않는다."""
        with self.database.session(write=True) as connection:
            row = connection.execute('''SELECT e.starts_at, e.duration_minutes FROM calendar_events e
                JOIN calendars c ON c.id=e.calendar_id WHERE e.id=? AND c.source='custom' ''',
                                     (entry_id,)).fetchone()
            if row is None:
                raise NotFoundError('이동할 사용자 일정을 찾을 수 없습니다.')
            original = datetime.fromisoformat(row['starts_at'])
            if original != expected_start:
                raise DatabaseError('일정이 변경되었습니다. 새로고침 후 다시 이동해 주세요.')
            try:
                moved = original.astimezone(KST) + timedelta(days=days)
                end = moved + timedelta(minutes=row['duration_minutes'])
                if not 2 <= moved.year <= 9998 or not 2 <= end.year <= 9998:
                    raise ValueError
            except (ValueError, OverflowError) as error:
                raise DatabaseError('이동 가능한 날짜 범위를 벗어났습니다.') from error
            connection.execute('UPDATE calendar_events SET starts_at=?, updated_at=? WHERE id=?',
                               (utc_text(moved), now_text(), entry_id))

    def save_event(self, value: CalendarEventInput, entry_id: int | None = None):
        data = values(CalendarEventInput.model_validate(value.model_dump(include=set(CalendarEventInput.model_fields))))
        data['now'] = now_text()
        with self.database.session(write=True) as connection:
            target = connection.execute("SELECT id FROM calendars WHERE id=? AND source='custom'", (value.calendar_id,)).fetchone()
            if target is None:
                raise NotFoundError('일정을 등록할 사용자 캘린더를 찾을 수 없습니다.')
            if entry_id is None:
                connection.execute('''INSERT INTO calendar_events
                    (calendar_id, title, starts_at, duration_minutes, location, content, all_day, created_at, updated_at)
                    VALUES (:calendar_id, :title, :starts_at, :duration_minutes, :location, :content, :all_day, :now, :now)''', data)
            else:
                data['id'] = entry_id
                cursor = connection.execute('''UPDATE calendar_events SET title=:title, starts_at=:starts_at,
                    duration_minutes=:duration_minutes, location=:location, content=:content, all_day=:all_day, updated_at=:now
                    WHERE id=:id AND calendar_id=:calendar_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('일정을 찾을 수 없습니다.')
