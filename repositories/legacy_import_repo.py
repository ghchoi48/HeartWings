"""기존 XLSB 자료를 한 트랜잭션으로 추가한다."""

from dataclasses import replace

from models import StudentInput, TeacherInput, ConsultationInput, PsychologicalTestInput, CounselingInput
from repositories._support import now_text, values
from repositories.student_repo import StudentRepository
from services.legacy_import import parse_legacy


class LegacyImportRepository:
    def __init__(self, database):
        self.database = database

    def _errors(self, connection, batch):
        errors = list(batch.errors)
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_imports'").fetchone()
        if exists and connection.execute('SELECT 1 FROM legacy_imports WHERE fingerprint=?', (batch.fingerprint,)).fetchone():
            errors.append('이미 가져온 원본 자료입니다.')
        students = {tuple(row) for row in connection.execute('''SELECT s.name, e.school_year, e.grade, e.classroom
            FROM students s JOIN student_enrollments e ON e.student_id=s.id''')}
        groups = {row[0] for row in connection.execute('SELECT name FROM counseling_groups')}
        teachers = {row[0] for row in connection.execute('SELECT name FROM teachers')}
        for person in batch.people:
            value = person.value
            if isinstance(value, StudentInput):
                identity = (value.name, value.school_year, value.grade, value.classroom)
                duplicate = identity in students
                students.add(identity)
            elif isinstance(value, TeacherInput):
                duplicate = value.name in teachers
                teachers.add(value.name)
            else:
                duplicate = value.name in groups
                groups.add(value.name)
            if duplicate:
                errors.append(f'인적사항등록 {person.row}행: 같은 학생(이름·학년도·학년·반), 교사명 또는 집단명이 있습니다. 자동 병합하지 않습니다.')
        return errors

    def preview(self, content, school_year, period_times=None):
        batch = parse_legacy(content, school_year, period_times)
        with self.database.session() as connection:
            return replace(batch, errors=tuple(self._errors(connection, batch)))

    def save(self, batch):
        if batch.errors or not batch.people:
            raise ValueError('파일 오류를 수정하고 다시 검사하세요.')
        with self.database.session(write=True) as connection:
            errors = self._errors(connection, batch)
            if errors:
                raise ValueError('\n'.join(errors[:30]))
            # 이관 이력 역시 암호화된 DB에 보관하고 데이터와 함께 커밋한다.
            connection.execute('''CREATE TABLE IF NOT EXISTS legacy_imports (
                fingerprint TEXT PRIMARY KEY, imported_at TEXT NOT NULL)''')
            ids, cases = {}, {}
            timestamp = now_text()

            def insert(table, data):
                # 테이블/열은 코드 내 모델로만 구성한다. 원본 값은 모두 바인딩한다.
                data = dict(data, created_at=timestamp, updated_at=timestamp)
                columns = ','.join(data)
                return connection.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in data)})',
                                          tuple(data.values())).lastrowid

            for person in batch.people:
                data = values(person.value)
                if isinstance(person.value, StudentInput):
                    ids[person.key] = insert('students', data)
                    StudentRepository._save_enrollment(connection, ids[person.key], data)
                elif isinstance(person.value, TeacherInput):
                    ids[person.key] = insert('teachers', data)
                else:
                    data.pop('student_ids')
                    ids[person.key] = insert('counseling_groups', data)
            for log in batch.logs:
                data = values(log.value)
                if log.author:
                    data['author'] = log.author
                if isinstance(log.value, ConsultationInput):
                    data['teacher_id'] = ids[log.key]
                    table = 'consultations'
                elif isinstance(log.value, PsychologicalTestInput):
                    data['student_id'] = ids[log.key]
                    table = 'psychological_tests'
                elif isinstance(log.value, CounselingInput):
                    if log.key not in cases:
                        cases[log.key] = insert('counseling_cases', dict(student_id=ids[log.key], title=f'이관 사례 {log.key}'[:200]))
                    data.update(student_id=ids[log.key], case_id=cases[log.key])
                    table = 'counseling'
                else:
                    data['group_id'] = ids[log.key]
                    table = 'group_counseling_logs'
                log_id = insert(table, data)
                # 일반 작성자 트리거는 현재 교사를 기록한다. 이관은 원본 작성자를 보존한다.
                if log.author:
                    connection.execute(f'UPDATE {table} SET author=? WHERE id=?', (log.author, log_id))
            connection.execute('INSERT INTO legacy_imports VALUES (?, ?)', (batch.fingerprint, timestamp))
        self.database.student_revision += 1
        return len(batch.people), len(batch.logs)
