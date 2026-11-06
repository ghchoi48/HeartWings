"""업로드 서식에 필요한 메타데이터만 한 읽기 트랜잭션에서 조회한다."""
from dataclasses import dataclass
from datetime import date, datetime

from maeumnarae.core.database import Database
from maeumnarae.services.reports.reporting import KST


@dataclass(frozen=True)
class JournalSnapshot:
    records: tuple[dict, ...]
    members: dict[int, tuple[int, ...]]
    students: tuple[dict, ...] = ()


class JournalExportRepository:
    def __init__(self, database: Database):
        self.database = database

    def school_years(self) -> list[int]:
        """모든 내보내기 대상 일지의 날짜에서 학년도를 구한다."""
        with self.database.session() as connection:
            timestamps = connection.execute('''
                SELECT starts_at FROM counseling
                UNION SELECT starts_at FROM special_education_logs
                UNION SELECT l.starts_at FROM group_counseling_logs l
                    JOIN counseling_groups g ON g.id=l.group_id
                UNION SELECT starts_at FROM consultations''').fetchall()
            days = connection.execute('''
                SELECT test_date AS day FROM psychological_tests
                UNION SELECT event_date AS day FROM education_events''').fetchall()
        dates = [datetime.fromisoformat(row['starts_at']).astimezone(KST).date() for row in timestamps]
        dates.extend(date.fromisoformat(row['day']) for row in days)
        return sorted({day.year if day.month >= 3 else day.year - 1 for day in dates}, reverse=True)

    def snapshot(self, *, include_students=False) -> JournalSnapshot:
        # 학생 명부는 상담 대장 요청에만 포함한다. 연락처·본문·비밀 메모는 조회하지 않는다.
        with self.database.session() as connection:
            records = []
            records.extend(dict(row, kind='individual') for row in connection.execute('''
                SELECT id, student_id, starts_at, duration_minutes, status,
                       counseling_area AS area, counseling_target AS target, counseling_method AS method
                FROM counseling'''))
            records.extend(dict(row, kind='special') for row in connection.execute('''
                SELECT l.id, l.student_id, l.starts_at, l.duration_minutes, l.status,
                       l.counseling_area AS area, l.counseling_target AS target,
                       l.counseling_method AS method, e.law
                FROM special_education_logs l LEFT JOIN special_educations e ON e.id=l.case_id'''))
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
                SELECT id, event_date AS day, event_time AS clock, duration_minutes, category, participant_count FROM education_events'''))
            members = {}
            for row in connection.execute('SELECT group_id, student_id FROM group_counseling_members ORDER BY student_id'):
                members.setdefault(row['group_id'], []).append(row['student_id'])
            students = tuple(dict(row) for row in connection.execute(
                'SELECT id, grade, classroom, student_number, gender, name FROM students ORDER BY id'
            )) if include_students else ()
        return JournalSnapshot(tuple(records), {key: tuple(value) for key, value in members.items()}, students)
