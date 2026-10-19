"""자문 대상 교사의 조회와 저장."""

from database import Database, NotFoundError
from models import Teacher, TeacherInput
from repositories._support import check_page, now_text, values


class TeacherRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self, *, limit: int = 100, offset: int = 0) -> list[Teacher]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute(
                'SELECT * FROM teachers ORDER BY name, id LIMIT ? OFFSET ?',
                (limit, offset)).fetchall()
            return [Teacher.model_validate(dict(row)) for row in rows]

    def get(self, teacher_id: int) -> Teacher | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM teachers WHERE id=?', (teacher_id,)).fetchone()
            return Teacher.model_validate(dict(row)) if row else None

    def save(self, value: TeacherInput, teacher_id: int | None = None) -> Teacher:
        data = values(TeacherInput.model_validate(value.model_dump(include=set(TeacherInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if teacher_id is None:
                cursor = connection.execute('''INSERT INTO teachers
                    (name, contact, extension, responsibilities, created_at, updated_at)
                    VALUES (:name, :contact, :extension, :responsibilities, :updated_at, :updated_at)''', data)
                teacher_id = cursor.lastrowid
            else:
                data['id'] = teacher_id
                cursor = connection.execute('''UPDATE teachers SET name=:name, contact=:contact,
                    extension=:extension, responsibilities=:responsibilities, updated_at=:updated_at
                    WHERE id=:id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('교사를 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM teachers WHERE id=?', (teacher_id,)).fetchone()
            return Teacher.model_validate(dict(row))
