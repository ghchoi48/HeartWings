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
        """동일 스냅샷에서 전체 상태와 완료 상담의 유형·월·현재 학년 통계를 집계한다."""
        params = self._params(start, end)
        with self.database.session() as connection:
            summary = connection.execute('''SELECT count(*) AS total,
                coalesce(sum(status='completed'), 0) AS completed,
                count(DISTINCT CASE WHEN status='completed' THEN student_id END) AS students,
                coalesce(sum(CASE WHEN status='completed' THEN duration_minutes ELSE 0 END), 0) AS minutes
                FROM counseling WHERE starts_at >= :start AND starts_at < :end''', params).fetchone()
            status_rows = connection.execute('''SELECT status AS label, count(*) AS count FROM counseling
                WHERE starts_at >= :start AND starts_at < :end GROUP BY status''', params).fetchall()
            counts = {row['label']: row['count'] for row in status_rows}
            groups = {}
            # 아래 SQL 식은 고정된 내부 값이다. 사용자 입력은 모두 매개변수로 바인딩한다.
            for key, expression in [('categories', 'c.category'), ('months', "strftime('%Y-%m', substr(c.starts_at, 1, 19), '+9 hours')"),
                                    ('grades', "CASE WHEN s.status='졸업' THEN '졸업' ELSE s.grade END")]:
                rows = connection.execute(f'''SELECT {expression} AS label, count(*) AS count
                    FROM counseling c JOIN students s ON s.id=c.student_id
                    WHERE c.starts_at >= :start AND c.starts_at < :end AND c.status='completed'
                    GROUP BY {expression} ORDER BY {expression}''', params).fetchall()
                groups[key] = tuple(ReportBucket(str(row['label']), row['count']) for row in rows)
            return CounselingReport(start, end, **dict(summary),
                statuses=tuple(ReportBucket(key, counts.get(key, 0)) for key in ('scheduled', 'completed', 'cancelled')), **groups)
