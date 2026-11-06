"""상담 사례 및 사례 개념화 보고서 저장소."""

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import CounselingCase, CounselingCaseInput
from maeumnarae.repositories.shared._support import now_text, values


class CaseRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self, student_id: int) -> list[CounselingCase]:
        with self.database.session() as connection:
            rows = connection.execute(
                'SELECT * FROM counseling_cases WHERE student_id=? ORDER BY id DESC', (student_id,)).fetchall()
            return [CounselingCase.model_validate(dict(row)) for row in rows]

    def save(self, value: CounselingCaseInput, case_id: int | None = None, report_field: str = 'report_html') -> CounselingCase:
        if report_field not in ('report_html', 'intake_html', 'closing_html'):
            raise ValueError('지원하지 않는 보고서입니다.')
        data = values(CounselingCaseInput.model_validate(value.model_dump(include=set(CounselingCaseInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if case_id is None:
                cursor = connection.execute('''INSERT INTO counseling_cases
                    (student_id, title, report_html, intake_html, closing_html, created_at, updated_at)
                    VALUES (:student_id, :title, :report_html, :intake_html, :closing_html, :updated_at, :updated_at)''', data)
                case_id = cursor.lastrowid
            else:
                data['id'] = case_id
                cursor = connection.execute(f'''UPDATE counseling_cases SET title=:title,
                    {report_field}=:{report_field}, updated_at=:updated_at
                    WHERE id=:id AND student_id=:student_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('상담 사례를 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM counseling_cases WHERE id=?', (case_id,)).fetchone()
            return CounselingCase.model_validate(dict(row))
