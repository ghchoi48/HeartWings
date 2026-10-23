"""업로드 서식에 필요한 메타데이터만 한 읽기 트랜잭션에서 조회한다."""
from dataclasses import dataclass

from database import Database


@dataclass(frozen=True)
class JournalSnapshot:
    records: tuple[dict, ...]
    genders: dict[int, str | None]
    grades: dict[tuple[int, int], int]
    members: dict[int, tuple[int, ...]]


class JournalExportRepository:
    def __init__(self, database: Database):
        self.database = database

    def snapshot(self) -> JournalSnapshot:
        # 이름·연락처·제목·본문·비밀 메모는 조회하지 않는다.
        with self.database.session() as connection:
            records = []
            for kind, table in (('individual', 'counseling'), ('special', 'special_education_logs')):
                records.extend(dict(row, kind=kind) for row in connection.execute(f'''
                    SELECT id, student_id, starts_at, duration_minutes, status,
                           counseling_area AS area, counseling_target AS target, counseling_method AS method
                    FROM {table}'''))
            records.extend(dict(row, kind='group') for row in connection.execute('''
                SELECT l.id, l.group_id, l.starts_at, l.duration_minutes, l.status,
                       g.counseling_area AS area
                FROM group_counseling_logs l JOIN counseling_groups g ON g.id=l.group_id'''))
            records.extend(dict(row, kind='consultation') for row in connection.execute('''
                SELECT id, starts_at, duration_minutes, status, consultation_area AS area FROM consultations'''))
            records.extend(dict(row, kind='test') for row in connection.execute('''
                SELECT id, student_id, test_date AS day, test_time AS clock, duration_minutes, target
                FROM psychological_tests'''))
            records.extend(dict(row, kind='education') for row in connection.execute('''
                SELECT id, event_date AS day, event_time AS clock, duration_minutes, category FROM education_events'''))
            genders = {row['id']: row['gender'] for row in connection.execute('SELECT id, gender FROM students')}
            grades = {(row['student_id'], row['school_year']): row['grade'] for row in connection.execute(
                'SELECT student_id, school_year, grade FROM student_enrollments')}
            members = {}
            for row in connection.execute('SELECT group_id, student_id FROM group_counseling_members ORDER BY student_id'):
                members.setdefault(row['group_id'], []).append(row['student_id'])
        return JournalSnapshot(tuple(records), genders, grades, {key: tuple(value) for key, value in members.items()})
