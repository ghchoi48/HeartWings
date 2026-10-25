"""학생별 특별교육 등록 정보와 일지 저장소."""

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import SpecialEducation, SpecialEducationInput, Counseling, CounselingInput
from maeumnarae.repositories.attachment_repo import insert_attachments
from maeumnarae.repositories._support import check_page, now_text, values


class SpecialEducationRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self, student_id: int) -> list[SpecialEducation]:
        with self.database.session() as connection:
            rows = connection.execute('SELECT * FROM special_educations WHERE student_id=? ORDER BY id DESC',
                                      (student_id,)).fetchall()
            return [SpecialEducation.model_validate(dict(row)) for row in rows]

    def save(self, value: SpecialEducationInput, case_id: int | None = None) -> SpecialEducation:
        data = values(SpecialEducationInput.model_validate(value.model_dump(include=set(SpecialEducationInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if case_id is None:
                cursor = connection.execute('''INSERT INTO special_educations
                    (student_id, title, law, case_number, created_at, updated_at)
                    VALUES (:student_id, :title, :law, :case_number, :updated_at, :updated_at)''', data)
                case_id = cursor.lastrowid
            else:
                data['id'] = case_id
                cursor = connection.execute('''UPDATE special_educations SET title=:title, law=:law,
                    case_number=:case_number, updated_at=:updated_at WHERE id=:id AND student_id=:student_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('특별교육을 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM special_educations WHERE id=?', (case_id,)).fetchone()
            return SpecialEducation.model_validate(dict(row))


class SpecialEducationLogRepository:
    def __init__(self, database: Database):
        self.database = database

    def count(self, *, student_id: int, case_id: int) -> int:
        with self.database.session() as connection:
            return connection.execute('SELECT COUNT(*) FROM special_education_logs WHERE student_id=? AND case_id=?',
                                      (student_id, case_id)).fetchone()[0]

    def list(self, *, student_id: int, case_id: int, limit: int = 20, offset: int = 0) -> list[Counseling]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute('''SELECT * FROM special_education_logs WHERE student_id=? AND case_id=?
                ORDER BY starts_at DESC, id DESC LIMIT ? OFFSET ?''', (student_id, case_id, limit, offset)).fetchall()
            return [Counseling.model_validate(dict(row)) for row in rows]

    def get(self, entry_id: int) -> Counseling | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM special_education_logs WHERE id=?', (entry_id,)).fetchone()
            return Counseling.model_validate(dict(row)) if row else None

    def create(self, value: CounselingInput, *, attachments=()) -> Counseling:
        return self._save(value, attachments=attachments)

    def update(self, entry_id: int, value: CounselingInput) -> Counseling:
        return self._save(value, entry_id)

    def _save(self, value: CounselingInput, entry_id: int | None = None, *, attachments=()) -> Counseling:
        data = values(CounselingInput.model_validate(value.model_dump(include=set(CounselingInput.model_fields))))
        if data['case_id'] is None:
            raise ValueError('특별교육을 선택해 주세요.')
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if entry_id is None:
                cursor = connection.execute('''INSERT INTO special_education_logs
                    (student_id, case_id, starts_at, duration_minutes, category, status, title, content_markdown,
                     content_format, counseling_method, counseling_target, counseling_area, follow_up, created_at, updated_at)
                    VALUES (:student_id, :case_id, :starts_at, :duration_minutes, :category, :status, :title,
                            :content_markdown, :content_format, :counseling_method, :counseling_target,
                            :counseling_area, :follow_up, :updated_at, :updated_at)''', data)
                entry_id = cursor.lastrowid
            else:
                data['id'] = entry_id
                cursor = connection.execute('''UPDATE special_education_logs SET starts_at=:starts_at,
                    duration_minutes=:duration_minutes, category=:category, status=:status, title=:title,
                    content_markdown=:content_markdown, content_format=:content_format,
                    counseling_method=:counseling_method, counseling_target=:counseling_target,
                    counseling_area=:counseling_area, follow_up=:follow_up, updated_at=:updated_at
                    WHERE id=:id AND student_id=:student_id AND case_id=:case_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('특별 교육 일지를 찾을 수 없습니다.')
            insert_attachments(connection, 'special_log', entry_id, attachments)
            row = connection.execute('SELECT * FROM special_education_logs WHERE id=?', (entry_id,)).fetchone()
            return Counseling.model_validate(dict(row))
