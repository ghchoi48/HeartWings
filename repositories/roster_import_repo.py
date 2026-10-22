"""명부 일괄 등록의 기존 자료 중복 검사와 원자적 저장."""

from dataclasses import replace

from database import Database
from repositories.student_repo import StudentRepository
from repositories.teacher_repo import TeacherRepository
from services.roster_import import ImportBatch, parse_import


class RosterImportRepository:
    def __init__(self, database: Database):
        self.database = database

    def check(self, batch: ImportBatch) -> ImportBatch:
        errors = list(batch.errors)
        with self.database.session() as connection:
            if batch.kind == 'students':
                existing = {tuple(row) for row in connection.execute(
                    'SELECT school_year, grade, classroom, student_number FROM student_enrollments WHERE student_number IS NOT NULL')}
                for row in batch.rows:
                    value = row.value
                    if value.student_number and (value.school_year, value.grade, value.classroom, value.student_number) in existing:
                        errors.append(f'{row.number}행: 같은 학년도·학년·반에 이미 등록된 학생 번호입니다.')
            else:
                existing = {tuple(row) for row in connection.execute(
                    'SELECT name, contact, extension, responsibilities FROM teachers')}
                for row in batch.rows:
                    value = row.value
                    if (value.name, value.contact, value.extension, value.responsibilities) in existing:
                        errors.append(f'{row.number}행: 모든 정보가 같은 교사가 이미 등록되어 있습니다.')
        return replace(batch, errors=tuple(errors))

    def preview(self, content: bytes, kind: str) -> ImportBatch:
        return self.check(parse_import(content, kind))

    def save(self, batch: ImportBatch) -> int:
        if batch.errors or not batch.rows:
            raise ValueError('파일의 오류를 수정하고 다시 업로드해 주세요.')
        # 검증 이후 추가된 자료도 재검사하고 앱 내의 다른 쓰기와 경합하지 않게 한다.
        with self.database._session_lock:
            checked = self.check(batch)
            if checked.errors:
                raise ValueError('\n'.join(checked.errors[:20]))
            values = [row.value for row in batch.rows]
            if batch.kind == 'students':
                StudentRepository(self.database).create_many(values)
            else:
                TeacherRepository(self.database).create_many(values)
        return len(batch.rows)
