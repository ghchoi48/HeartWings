"""학생 CRUD 및 검색. SQL은 이 모듈 내부에만 위치한다."""

import json

from maeumnarae.core.database import ConflictError, Database, NotFoundError
from maeumnarae.core.models import FamilyInput, Student, StudentInput, StudentEnrollment, StudentEnrollmentInput
from maeumnarae.repositories.shared._support import check_page, now_text, values


class StudentRepository:
    """DB를 주입받아 학생을 관리한다. 이름이 같은 학생은 별개로 저장한다."""

    def __init__(self, database: Database):
        self.database = database

    def create(self, student: StudentInput) -> Student:
        """학생을 추가하고 ID와 타임스탬프가 포함된 모델을 반환한다."""
        return self.create_many([student])[0]

    def enrollments(self, student_id: int) -> list[StudentEnrollment]:
        with self.database.session() as connection:
            return [StudentEnrollment.model_validate(dict(row)) for row in connection.execute(
                'SELECT * FROM student_enrollments WHERE student_id=? ORDER BY school_year DESC',
                (student_id,))]

    @staticmethod
    def _save_enrollment(connection, student_id: int, data: dict) -> None:
        enrollment = values(StudentEnrollmentInput.model_validate(
            {key: data[key] for key in StudentEnrollmentInput.model_fields}))
        enrollment.update(student_id=student_id, timestamp=now_text())
        connection.execute('''INSERT INTO student_enrollments
            (student_id, school_year, grade, classroom, student_number, status, created_at, updated_at)
            VALUES (:student_id, :school_year, :grade, :classroom, :student_number, :status, :timestamp, :timestamp)
            ON CONFLICT(student_id, school_year) DO UPDATE SET
                grade=excluded.grade, classroom=excluded.classroom, status=excluded.status,
                student_number=excluded.student_number, updated_at=excluded.updated_at''', enrollment)
        connection.execute('''UPDATE students SET (school_year, grade, classroom, student_number, status) =
            (SELECT school_year, grade, classroom, student_number, status FROM student_enrollments
             WHERE student_id=:student_id ORDER BY school_year DESC LIMIT 1), updated_at=:timestamp
            WHERE id=:student_id''', enrollment)

    def save_enrollment(self, student_id: int, value: StudentEnrollmentInput) -> Student:
        with self.database.session(write=True) as connection:
            if connection.execute('SELECT id FROM students WHERE id=?', (student_id,)).fetchone() is None:
                raise NotFoundError('학생을 찾을 수 없습니다.')
            self._save_enrollment(connection, student_id, values(value))
            row = connection.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
            saved = Student.model_validate(dict(row))
        self.database.student_revision += 1
        return saved

    def delete_enrollment(self, student_id: int, school_year: int) -> Student:
        """학적 한 건을 삭제하고 남은 최신 학적을 학생 정보에 반영한다."""
        with self.database.session(write=True) as connection:
            if connection.execute(
                    'SELECT 1 FROM student_enrollments WHERE student_id=? AND school_year=?',
                    (student_id, school_year)).fetchone() is None:
                raise NotFoundError('학적 이력을 찾을 수 없습니다.')
            latest = connection.execute('''SELECT school_year, grade, classroom, student_number, status
                FROM student_enrollments WHERE student_id=? AND school_year<>?
                ORDER BY school_year DESC LIMIT 1''', (student_id, school_year)).fetchone()
            if latest is None:
                raise ConflictError('학생의 학년·반 정보를 유지하려면 학적 이력이 최소 한 건 필요합니다.')
            connection.execute('DELETE FROM student_enrollments WHERE student_id=? AND school_year=?',
                               (student_id, school_year))
            connection.execute('''UPDATE students SET school_year=?, grade=?, classroom=?,
                student_number=?, status=?, updated_at=? WHERE id=?''',
                (latest['school_year'], latest['grade'], latest['classroom'], latest['student_number'], latest['status'],
                 now_text(), student_id))
            row = connection.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
            saved = Student.model_validate(dict(row))
        self.database.student_revision += 1
        return saved

    def create_many(self, students: list[StudentInput]) -> list[Student]:
        """모든 입력을 검증하고 한 트랜잭션으로 등록한다. 오류 시 전체 롤백한다."""
        data = [values(StudentInput.model_validate(
            student.model_dump(include=set(StudentInput.model_fields)))) for student in students]
        saved = []
        with self.database.session(write=True) as connection:
            for item in data:
                item['created_at'] = item['updated_at'] = now_text()
                item['nickname'] = item['nickname'] or ''
                cursor = connection.execute('''INSERT INTO students
                    (name, nickname, gender, school_year, student_number, grade, status, classroom, birth_date,
                     student_contact, guardian_contact, notes, created_at, updated_at)
                    VALUES (:name, :nickname, :gender, :school_year, :student_number, :grade, :status, :classroom, :birth_date,
                            :student_contact, :guardian_contact, :notes, :created_at, :updated_at)''', item)
                self._save_enrollment(connection, cursor.lastrowid, item)
                row = connection.execute('SELECT * FROM students WHERE id=?', (cursor.lastrowid,)).fetchone()
                saved.append(Student.model_validate(dict(row)))
        self.database.student_revision += len(saved)
        return saved

    def get(self, student_id: int) -> Student | None:
        """ID로 조회한다. 없는 학생은 None을 반환한다."""
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM students WHERE id = ?', (student_id,)).fetchone()
            return Student.model_validate(dict(row)) if row else None

    def list(self, *, search: str = '', grade: int | None = None,
             limit: int = 100, offset: int = 0,
             has_special_education_logs: bool = False) -> list[Student]:
        """이름/학번의 리터럴 부분 문자열 검색 및 학년 필터. 결과 순서는 고정한다."""
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute(
                '''SELECT * FROM students
                WHERE (instr(name, :search) > 0 OR instr(coalesce(student_number, ''), :search) > 0)
                  AND (:grade IS NULL OR grade = :grade)
                  AND (:has_special_education_logs = 0 OR EXISTS (
                      SELECT 1 FROM special_education_logs WHERE student_id = students.id))
                ORDER BY grade IS NULL, grade, classroom, name, id LIMIT :limit OFFSET :offset''',
                dict(search=search.strip(), grade=grade, limit=limit, offset=offset,
                     has_special_education_logs=has_special_education_logs)).fetchall()
            return [Student.model_validate(dict(row)) for row in rows]

    def update(self, student_id: int, student: StudentInput) -> Student:
        """입력 필드 전체를 교체한다. 생성 시각과 ID는 보존한다."""
        data = values(StudentInput.model_validate(student.model_dump(include=set(StudentInput.model_fields))))
        data.update(id=student_id, updated_at=now_text())
        data['nickname'] = data['nickname'] or ''
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                '''UPDATE students SET name=:name, birth_date=:birth_date,
                nickname=:nickname, gender=:gender, student_contact=:student_contact,
                guardian_contact=:guardian_contact, notes=:notes, updated_at=:updated_at
                WHERE id=:id''', data)
            if cursor.rowcount == 0:
                raise NotFoundError('학생을 찾을 수 없습니다.')
            self._save_enrollment(connection, student_id, data)
            row = connection.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
            saved = Student.model_validate(dict(row))
        self.database.student_revision += 1
        return saved

    def update_family(self, student_id: int, family: FamilyInput) -> Student:
        """다른 학생 필드를 덮어쓰지 않고 가족 정보만 갱신한다."""
        data = values(FamilyInput.model_validate(family.model_dump()))
        data['family_members'] = json.dumps(data['family_members'], ensure_ascii=False)
        data.update(id=student_id, updated_at=now_text())
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                '''UPDATE students SET guardian_contact=:guardian_contact,
                family_type=:family_type, family_welfare_type=:family_welfare_type,
                family_members=:family_members,
                updated_at=:updated_at WHERE id=:id''', data)
            if cursor.rowcount == 0:
                raise NotFoundError('학생을 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM students WHERE id=?', (student_id,)).fetchone()
            saved = Student.model_validate(dict(row))
        self.database.student_revision += 1
        return saved

    def delete(self, student_id: int) -> None:
        """상담 기록이 있는 학생은 FK RESTRICT로 삭제를 거부한다. 연쇄 삭제하지 않는다."""
        with self.database.session(write=True) as connection:
            if connection.execute('DELETE FROM students WHERE id=?', (student_id,)).rowcount == 0:
                raise NotFoundError('학생을 찾을 수 없습니다.')
        self.database.student_revision += 1
