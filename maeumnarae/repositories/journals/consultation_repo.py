"""교사별 자문 일지 저장 및 최신순 조회."""

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import Consultation, ConsultationInput
from maeumnarae.repositories.journals.attachment_repo import insert_attachments
from maeumnarae.repositories.shared._support import check_page, now_text, values


class ConsultationRepository:
    def __init__(self, database: Database):
        self.database = database

    def count(self, teacher_id: int) -> int:
        with self.database.session() as connection:
            return connection.execute('SELECT COUNT(*) FROM consultations WHERE teacher_id=?',
                                      (teacher_id,)).fetchone()[0]

    def list(self, teacher_id: int, *, limit: int = 20, offset: int = 0) -> list[Consultation]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute('''SELECT * FROM consultations WHERE teacher_id=?
                ORDER BY starts_at DESC, id DESC LIMIT ? OFFSET ?''', (teacher_id, limit, offset)).fetchall()
            return [Consultation.model_validate(dict(row)) for row in rows]

    def get(self, entry_id: int, teacher_id: int) -> Consultation | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM consultations WHERE id=? AND teacher_id=?',
                                     (entry_id, teacher_id)).fetchone()
            return Consultation.model_validate(dict(row)) if row else None

    def save(self, value: ConsultationInput, entry_id: int | None = None, *, attachments=()) -> Consultation:
        data = values(ConsultationInput.model_validate(value.model_dump(include=set(ConsultationInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if entry_id is None:
                cursor = connection.execute('''INSERT INTO consultations
                    (teacher_id, consultation_area, starts_at, duration_minutes, status, title, content_html, follow_up, created_at, updated_at)
                    VALUES (:teacher_id, :consultation_area, :starts_at, :duration_minutes, :status, :title, :content_html,
                            :follow_up, :updated_at, :updated_at)''', data)
                entry_id = cursor.lastrowid
            else:
                data['id'] = entry_id
                cursor = connection.execute('''UPDATE consultations SET starts_at=:starts_at, consultation_area=:consultation_area,
                    duration_minutes=:duration_minutes, status=:status, title=:title, content_html=:content_html,
                    follow_up=:follow_up, updated_at=:updated_at WHERE id=:id AND teacher_id=:teacher_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('자문 일지를 찾을 수 없습니다.')
            insert_attachments(connection, 'consultation', entry_id, attachments)
            row = connection.execute('SELECT * FROM consultations WHERE id=?', (entry_id,)).fetchone()
            return Consultation.model_validate(dict(row))
