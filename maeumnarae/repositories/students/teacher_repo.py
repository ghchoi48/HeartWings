"""자문 대상 교사의 조회와 저장."""

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import Teacher, TeacherInput
from maeumnarae.repositories.shared._support import check_page, now_text, values


class TeacherRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_many(self, teachers: list[TeacherInput]) -> list[Teacher]:
        """교사들을 한 트랜잭션으로 등록하여 부분 저장을 방지한다."""
        data = [values(TeacherInput.model_validate(
            teacher.model_dump(include=set(TeacherInput.model_fields)))) for teacher in teachers]
        saved = []
        with self.database.session(write=True) as connection:
            for item in data:
                item['now'] = now_text()
                cursor = connection.execute('''INSERT INTO teachers
                    (name, contact, extension, responsibilities, created_at, updated_at)
                    VALUES (:name, :contact, :extension, :responsibilities, :now, :now)''', item)
                row = connection.execute('SELECT * FROM teachers WHERE id=?', (cursor.lastrowid,)).fetchone()
                saved.append(Teacher.model_validate(dict(row)))
        return saved

    def list(self, *, limit: int = 100, offset: int = 0) -> list[Teacher]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute(
                'SELECT * FROM teachers ORDER BY name, id LIMIT ? OFFSET ?',
                (limit, offset)).fetchall()
            return [Teacher.model_validate(dict(row)) for row in rows]

    def search(self, query: str, *, limit: int = 50) -> list[Teacher]:
        """이름·내선 번호·담당 업무를 검색한다. LIKE 패턴 문자는 문자로 취급한다."""
        check_page(limit, 0)
        exact = query.strip()
        query = exact.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        with self.database.session() as connection:
            rows = connection.execute(
                """SELECT * FROM teachers WHERE name LIKE :contains ESCAPE '!'
                OR extension LIKE :contains ESCAPE '!'
                OR responsibilities LIKE :contains ESCAPE '!'
                ORDER BY CASE
                    WHEN name = :exact COLLATE NOCASE OR extension = :exact COLLATE NOCASE THEN 0
                    WHEN name LIKE :prefix ESCAPE '!' OR extension LIKE :prefix ESCAPE '!' THEN 1
                    WHEN name LIKE :contains ESCAPE '!' OR extension LIKE :contains ESCAPE '!' THEN 2
                    WHEN responsibilities = :exact COLLATE NOCASE THEN 3
                    WHEN responsibilities LIKE :prefix ESCAPE '!' THEN 4
                    ELSE 5 END,
                    length(name), name, id LIMIT :limit""",
                dict(contains=f'%{query}%', exact=exact, prefix=f'{query}%', limit=limit)).fetchall()
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
