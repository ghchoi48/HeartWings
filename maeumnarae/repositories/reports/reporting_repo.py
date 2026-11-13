"""캘린더 조회와 기간 통계 집계. 목록 페이지 제한 없이 SQL에서 전체 범위를 집계한다."""

from datetime import date, datetime

from maeumnarae.core.database import Database
from maeumnarae.core.models import CounselingReport, ReportBucket, ScheduleItem
from maeumnarae.services.reports.reporting import date_bounds
from maeumnarae.repositories.shared._support import check_page, utc_text


class ReportingRepository:
    """캘린더/통계용 읽기 전용 저장소. 본문이나 연락처를 조회하지 않는다."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _params(start: date, end: date, status: str | None = None) -> dict:
        if status not in (None, 'scheduled', 'completed', 'cancelled'):
            raise ValueError('지원하지 않는 상담 상태입니다.')
        lower, upper = date_bounds(start, end)
        return dict(start=utc_text(lower), end=utc_text(upper), status=status)

    def daily_counts(self, start: date, end: date, status: str | None = None) -> dict[date, int]:
        """KST 시작 날짜별 일정 수를 반환한다. 빈 날짜는 생략한다."""
        params = self._params(start, end, status)
        with self.database.session() as connection:
            # SQLite의 밀리초 반올림이 23:59:59.999999를 다음 날로 넘기지 않도록 초까지만 사용한다.
            rows = connection.execute('''SELECT date(substr(starts_at, 1, 19), '+9 hours') AS day, count(*) AS count
                FROM counseling WHERE starts_at >= :start AND starts_at < :end
                AND (:status IS NULL OR status=:status) GROUP BY day''', params).fetchall()
            return {date.fromisoformat(row['day']): row['count'] for row in rows}

    def day_items(self, day: date, *, status: str | None = None,
                  limit: int = 21, offset: int = 0) -> list[ScheduleItem]:
        """하루 일정의 최소 메타데이터를 시간순으로 조회한다."""
        check_page(limit, offset)
        params = self._params(day, day, status) | dict(limit=limit, offset=offset)
        with self.database.session() as connection:
            rows = connection.execute('''SELECT c.id, c.student_id, s.name AS student_name,
                c.title, c.starts_at, c.duration_minutes, c.status
                FROM counseling c JOIN students s ON s.id=c.student_id
                WHERE c.starts_at >= :start AND c.starts_at < :end
                AND (:status IS NULL OR c.status=:status)
                ORDER BY c.starts_at, c.id LIMIT :limit OFFSET :offset''', params).fetchall()
            return [ScheduleItem(**(dict(row) | {'starts_at': datetime.fromisoformat(row['starts_at'])})) for row in rows]

    def statistics(self, start: date, end: date) -> CounselingReport:
        """모든 일지를 같은 스냅샷에서 집계한다. 상태 없는 일지는 완료로 취급한다."""
        date_bounds(start, end)
        params = dict(start=start.isoformat(), end=end.isoformat())
        categories = ('개인상담', '학부모상담', '심리검사', '집단상담', '교육/행사', '특별교육', '자문')
        area_types = ('개인상담', '학부모상담', '집단상담', '자문')
        # 본문/연락처 없이 집계 메타데이터만 통합한다. 날짜 전용 일지는 이미 KST이다.
        cte = """WITH all_logs AS (
            SELECT 'counseling' AS source, id, student_id,
                date(substr(starts_at, 1, 19), '+9 hours') AS day,
                duration_minutes, status,
                CASE WHEN counseling_target='보호자(가족)' OR category='학부모상담'
                     THEN '학부모상담' ELSE '개인상담' END AS category,
                counseling_area AS area FROM counseling
            UNION ALL
            SELECT 'psychological', id, student_id, test_date,
                coalesce(duration_minutes, 0), 'completed', '심리검사', '' FROM psychological_tests
            UNION ALL
            SELECT 'group', l.id, NULL, date(substr(l.starts_at, 1, 19), '+9 hours'),
                l.duration_minutes, l.status, '집단상담', g.counseling_area
                FROM group_counseling_logs l JOIN counseling_groups g ON g.id=l.group_id
            UNION ALL
            SELECT 'education', id, NULL, event_date, coalesce(duration_minutes, 0),
                'completed', '교육/행사', '' FROM education_events
            UNION ALL
            SELECT 'special', id, student_id, date(substr(starts_at, 1, 19), '+9 hours'),
                duration_minutes, status, '특별교육', counseling_area FROM special_education_logs
            UNION ALL
            SELECT 'consultation', id, NULL, date(substr(starts_at, 1, 19), '+9 hours'),
                duration_minutes, status, '자문', consultation_area FROM consultations
        ), logs AS (
            SELECT * FROM all_logs WHERE day >= :start AND day <= :end
        ), participants AS (
            SELECT source, id, student_id FROM logs
                WHERE status='completed' AND student_id IS NOT NULL
            UNION
            SELECT l.source, l.id, json_extract(a.value, '$.student_id')
                FROM logs l JOIN group_counseling_logs g ON l.source='group' AND g.id=l.id,
                     json_each(g.attendance) a
                WHERE l.status='completed' AND json_extract(a.value, '$.attended')=1
        ) """
        with self.database.session() as connection:
            def query(sql):
                return connection.execute(cte + sql, params).fetchall()

            def buckets(rows):
                return tuple(ReportBucket(str(row['label']), row['count']) for row in rows)

            summary = query("""SELECT count(*) AS total,
                coalesce(sum(status='completed'), 0) AS completed,
                (SELECT count(DISTINCT student_id) FROM participants) AS students,
                coalesce(sum(CASE WHEN status='completed' THEN duration_minutes ELSE 0 END), 0) AS minutes
                FROM logs""")[0]
            types = {row['label']: row['count'] for row in query("""
                SELECT category AS label, count(*) AS count FROM logs
                WHERE status='completed' GROUP BY category""")}
            months = buckets(query("""SELECT substr(day, 1, 7) AS label, count(*) AS count
                FROM logs WHERE status='completed' GROUP BY label ORDER BY label"""))
            # 집단 회기는 같은 학년의 출석자가 여러 명이어도 해당 학년에 한 건만 센다.
            grades = buckets(query("""SELECT grade AS label, count(*) AS count FROM (
                SELECT DISTINCT p.source, p.id,
                    CASE WHEN s.status='졸업' THEN '졸업' ELSE s.grade END AS grade
                FROM participants p JOIN students s ON s.id=p.student_id
            ) GROUP BY grade ORDER BY grade"""))
            area_rows = query("""SELECT category, coalesce(nullif(trim(area), ''), '미지정') AS label,
                count(*) AS count FROM logs WHERE status='completed'
                GROUP BY category, label ORDER BY count DESC, label""")
            return CounselingReport(start, end, **dict(summary),
                categories=tuple(ReportBucket(key, types.get(key, 0)) for key in categories),
                months=months, grades=grades,
                areas=tuple((kind, buckets(row for row in area_rows if row['category'] == kind))
                            for kind in area_types))
