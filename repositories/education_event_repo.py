"""교육/행사 기록의 조회와 저장."""
from database import Database, NotFoundError
from models import EducationEvent, EducationEventInput
from repositories._support import check_page, now_text, values


class EducationEventRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self, *, limit=100, offset=0) -> list[EducationEvent]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute(
                'SELECT * FROM education_events ORDER BY event_date DESC, id DESC LIMIT ? OFFSET ?',
                (limit, offset)).fetchall()
            return [EducationEvent.model_validate(dict(row)) for row in rows]

    def get(self, event_id: int) -> EducationEvent | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM education_events WHERE id=?', (event_id,)).fetchone()
            return EducationEvent.model_validate(dict(row)) if row else None

    def save(self, value: EducationEventInput, event_id: int | None = None) -> EducationEvent:
        data = values(EducationEventInput.model_validate(value.model_dump(include=set(EducationEventInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if event_id is None:
                cursor = connection.execute('''INSERT INTO education_events
                    (title, category, event_date, event_time, duration_minutes, location, audience, facilitator, content, content_format, created_at, updated_at)
                    VALUES (:title, :category, :event_date, :event_time, :duration_minutes, :location, :audience, :facilitator, :content, :content_format,
                            :updated_at, :updated_at)''', data)
                event_id = cursor.lastrowid
            else:
                data['id'] = event_id
                cursor = connection.execute('''UPDATE education_events SET title=:title, category=:category,
                    event_date=:event_date, event_time=:event_time, duration_minutes=:duration_minutes,
                    location=:location, audience=:audience, facilitator=:facilitator,
                    content=:content, content_format=:content_format, updated_at=:updated_at WHERE id=:id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('교육/행사를 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM education_events WHERE id=?', (event_id,)).fetchone()
            return EducationEvent.model_validate(dict(row))
