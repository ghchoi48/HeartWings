"""명시적으로 확인한 항목과 종속 기록을 한 트랜잭션에서 삭제한다."""

from maeumnarae.core.database import Database, NotFoundError


# 테이블 이름은 사용자 입력이 아닌 이 허용 목록에서만 선택한다.
TARGETS = {
    'student': ('students', '학생 정보', '학적·가족 정보, 개인 상담 사례와 일지, 특별교육, 심리검사 및 연결된 일정도 삭제됩니다. 집단 상담은 보존하고 참여 연결만 해제합니다.'),
    'teacher': ('teachers', '교사 정보', '이 교사의 자문 일지와 연결된 일정도 삭제됩니다.'),
    'case': ('counseling_cases', '상담 사례', '이 사례의 모든 상담 일지와 연결된 일정도 삭제됩니다.'),
    'counseling': ('counseling', '상담 일지', '연결된 상담 일정도 삭제됩니다.'),
    'special': ('special_educations', '특별 교육', '이 특별 교육의 모든 일지와 연결된 일정도 삭제됩니다.'),
    'special_log': ('special_education_logs', '특별 교육 일지', '연결된 특별교육 일정도 삭제됩니다.'),
    'group': ('counseling_groups', '집단 상담', '참여 연결, 모든 집단 상담 일지와 연결된 일정도 삭제됩니다. 학생 정보는 보존합니다.'),
    'group_log': ('group_counseling_logs', '집단 상담 일지', '연결된 상담 일정도 삭제됩니다.'),
    'consultation': ('consultations', '자문 일지', '연결된 자문 일정도 삭제됩니다.'),
    'test': ('psychological_tests', '심리검사 일지', ''),
    'education': ('education_events', '교육/행사', ''),
    'event': ('calendar_events', '일정', ''),
}


class DeletionRepository:
    def __init__(self, database: Database):
        self.database = database

    def delete(self, kind: str, record_id: int) -> None:
        table, label, _ = TARGETS[kind]
        with self.database.session(write=True) as connection:
            if connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (record_id,)).fetchone() is None:
                raise NotFoundError(f'{label}을(를) 찾을 수 없습니다. 목록을 새로고침해 주세요.')
            if kind == 'student':
                for child in ('counseling', 'special_education_logs', 'special_educations',
                              'psychological_tests', 'group_counseling_members', 'counseling_cases'):
                    connection.execute(f'DELETE FROM {child} WHERE student_id=?', (record_id,))
            elif kind == 'teacher':
                connection.execute('DELETE FROM consultations WHERE teacher_id=?', (record_id,))
            elif kind == 'case':
                connection.execute('DELETE FROM counseling WHERE case_id=?', (record_id,))
            elif kind == 'special':
                connection.execute('DELETE FROM special_education_logs WHERE case_id=?', (record_id,))
            elif kind == 'group':
                connection.execute('DELETE FROM group_counseling_logs WHERE group_id=?', (record_id,))
            connection.execute(f'DELETE FROM {table} WHERE id=?', (record_id,))
        if kind == 'student':
            self.database.student_revision += 1
