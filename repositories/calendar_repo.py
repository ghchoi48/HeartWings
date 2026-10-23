"""캘린더 설정과 사용자 일정, 개인상담·집단상담·자문·특별교육 일정의 통합 조회."""
from datetime import date

from database import Database, NotFoundError
from calendar_holidays import HOLIDAY_CALENDAR_ID, HOLIDAY_COLOR
from models import Calendar, CalendarInput, CalendarEvent, CalendarEventInput
from repositories._support import now_text, values
from repositories.reporting_repo import ReportingRepository


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
            return calendars + [Calendar(id=HOLIDAY_CALENDAR_ID, name='대한민국 공휴일', color=HOLIDAY_COLOR,
                                         source='holidays', visible=bool(visible))]

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
                    s.name, e.author, s.name || ' · 특별교육', s.id, '', '', 0
                FROM special_education_logs e JOIN students s ON s.id=e.student_id
                    JOIN calendars c ON c.source='counseling'
                WHERE c.id IN ({slots}) AND e.starts_at<:end
                    AND julianday(e.starts_at) + e.duration_minutes / 1440.0 > julianday(:start)
                    AND (:status IS NULL OR e.status=:status)
                ORDER BY starts_at, calendar_id, source, id''', params).fetchall()
            return [CalendarEvent.model_validate(dict(row)) for row in rows]

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
