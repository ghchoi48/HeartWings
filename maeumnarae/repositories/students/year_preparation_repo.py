"""새 학년도 초안 스냅샷과 단일 트랜잭션 확정 저장."""
import hashlib
import json

from maeumnarae.core.database import ConflictError
from maeumnarae.core.models import StudentInput, TeacherInput
from maeumnarae.repositories.shared._support import now_text, values
from maeumnarae.repositories.students.student_repo import StudentRepository
from maeumnarae.services.students.roster_import import parse_import
from maeumnarae.services.students.year_preparation import prepare_draft


class YearPreparationRepository:
    def __init__(self, database):
        self.database = database

    def school_years(self) -> list[int]:
        """기준 학년도 선택에 사용할 학적의 학년도 목록."""
        with self.database.session() as connection:
            return [row['school_year'] for row in connection.execute(
                'SELECT DISTINCT school_year FROM student_enrollments ORDER BY school_year DESC')]

    @staticmethod
    def _snapshot(connection, kind, base_year):
        school = connection.execute('SELECT school_level FROM school_settings WHERE id=1').fetchone()
        level = school['school_level'] if school else '중학교'
        if kind == 'students':
            enrollments = [dict(r) for r in connection.execute(
                'SELECT * FROM student_enrollments WHERE school_year IN (?, ?) ORDER BY student_id, school_year',
                (base_year, base_year + 1))]
            people = [dict(r) for r in connection.execute('''SELECT * FROM students WHERE id IN
                (SELECT student_id FROM student_enrollments WHERE school_year IN (?, ?)) ORDER BY id''',
                (base_year, base_year + 1))]
        else:
            people = [dict(r) for r in connection.execute('SELECT * FROM teachers ORDER BY id')]
            enrollments = []
        digest = hashlib.sha256(json.dumps([level, people, enrollments], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {p['id']: p for p in people}, {(e['student_id'], e['school_year']): e for e in enrollments}, level, digest

    def preview(self, content, kind, base_year):
        batch = parse_import(content, kind, target_year=base_year + 1 if kind == 'students' else None)
        with self.database.session() as connection:
            people, enrollments, level, snapshot = self._snapshot(connection, kind, base_year)
        return prepare_draft(batch, base_year, 6 if level == '초등학교' else 0 if level == 'Wee센터' else 3,
                             people, enrollments, snapshot)

    def save(self, draft):
        if draft.consumed:
            raise ValueError('이미 확정한 작업입니다.')
        entries = draft.validate()
        if not entries or any(e['error'] for e in entries):
            raise ValueError('미해결 항목과 오류를 모두 수정하세요.')
        with self.database.session(write=True) as connection:
            if draft.consumed:
                raise ValueError('이미 확정한 작업입니다.')
            if self._snapshot(connection, draft.kind, draft.base_year)[3] != draft.snapshot:
                raise ConflictError('검토 중 명단 또는 학교 정보가 변경되었습니다. 파일을 다시 업로드하여 재검토하세요.')
            if draft.kind == 'students':
                connection.execute('UPDATE student_enrollments SET student_number=NULL WHERE school_year=?', (draft.target_year,))
            for entry in entries:
                model = StudentInput if draft.kind == 'students' else TeacherInput
                data = values(model.model_validate(entry['value']))
                pid = entry['person_id']
                data['updated_at'] = now_text()
                if pid is None:
                    data['created_at'] = data['updated_at']
                    keys = list(data)
                    table = 'students' if draft.kind == 'students' else 'teachers'
                    cursor = connection.execute(f'INSERT INTO {table} ({", ".join(keys)}) VALUES ({", ".join(":" + k for k in keys)})', data)
                    pid = cursor.lastrowid
                else:
                    data['id'] = pid
                    excluded = {'id', 'school_year', 'grade', 'classroom', 'student_number', 'status'} if draft.kind == 'students' else {'id'}
                    keys = [k for k in data if k not in excluded]
                    table = 'students' if draft.kind == 'students' else 'teachers'
                    connection.execute(f'UPDATE {table} SET {", ".join(k + "=:" + k for k in keys)} WHERE id=:id', data)
                if draft.kind == 'students':
                    StudentRepository._save_enrollment(connection, pid, data)
        draft.consumed = True
        if draft.kind == 'students':
            self.database.student_revision += 1
        return len(entries)
