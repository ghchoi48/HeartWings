"""학생별 심리검사 일지 저장과 조회."""
from database import Database, NotFoundError
from models import PsychologicalTest, PsychologicalTestInput
from repositories._support import check_page, now_text, values


class PsychologicalTestRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self, student_id: int, *, limit=20, offset=0) -> list[PsychologicalTest]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute(
                'SELECT * FROM psychological_tests WHERE student_id=? ORDER BY test_date DESC, id DESC LIMIT ? OFFSET ?',
                (student_id, limit, offset)).fetchall()
            return [PsychologicalTest.model_validate(dict(row)) for row in rows]

    def save(self, value: PsychologicalTestInput, entry_id: int | None = None) -> PsychologicalTest:
        data = values(PsychologicalTestInput.model_validate(value.model_dump(include=set(PsychologicalTestInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if entry_id is None:
                cursor = connection.execute('''INSERT INTO psychological_tests
                    (student_id, title, test_date, target, test_time, duration_minutes, content, content_format, created_at, updated_at)
                    VALUES (:student_id, :title, :test_date, :target, :test_time, :duration_minutes, :content, :content_format, :updated_at, :updated_at)''', data)
                entry_id = cursor.lastrowid
            else:
                data['id'] = entry_id
                cursor = connection.execute('''UPDATE psychological_tests SET title=:title,
                    test_date=:test_date, target=:target, test_time=:test_time,
                    duration_minutes=:duration_minutes, content=:content, content_format=:content_format, updated_at=:updated_at
                    WHERE id=:id AND student_id=:student_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('심리검사 일지를 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM psychological_tests WHERE id=?', (entry_id,)).fetchone()
            return PsychologicalTest.model_validate(dict(row))
