"""상담 일정/마크다운 일지 CRUD와 타임라인/캘린더용 기간 조회."""

from datetime import datetime

from database import Database, NotFoundError
from models import Counseling, CounselingInput
from repositories._support import check_page, now_text, utc_text, values


class CounselingRepository:
    """SQLCipher 연결을 주입받아 상담 데이터를 관리한다."""

    def __init__(self, database: Database):
        self.database = database

    def create(self, counseling: CounselingInput) -> Counseling:
        """존재하는 학생의 상담을 추가한다. 마크다운 원문을 보존한다."""
        data = values(CounselingInput.model_validate(counseling.model_dump(include=set(CounselingInput.model_fields))))
        data['created_at'] = data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                '''INSERT INTO counseling
                (student_id, starts_at, duration_minutes, category, status, title,
                 content_markdown, follow_up, created_at, updated_at)
                VALUES (:student_id, :starts_at, :duration_minutes, :category, :status, :title,
                        :content_markdown, :follow_up, :created_at, :updated_at)''', data)
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (cursor.lastrowid,)).fetchone()
            return Counseling.model_validate(dict(row))

    def get(self, counseling_id: int) -> Counseling | None:
        """ID로 조회하며 없으면 None을 반환한다."""
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (counseling_id,)).fetchone()
            return Counseling.model_validate(dict(row)) if row else None

    def list(self, *, student_id: int | None = None, start: datetime | None = None,
             end: datetime | None = None, limit: int = 100, offset: int = 0) -> list[Counseling]:
        """시작 시각 기준 [start, end) 범위 조회. 최신순이며 시간대 변환은 UI 책임이다."""
        check_page(limit, offset)
        start_text = utc_text(start) if start is not None else None
        end_text = utc_text(end) if end is not None else None
        if start_text and end_text and start_text >= end_text:
            raise ValueError('종료 시각은 시작 시각보다 늦어야 합니다.')
        with self.database.session() as connection:
            rows = connection.execute(
                '''SELECT * FROM counseling
                WHERE (:student_id IS NULL OR student_id=:student_id)
                  AND (:start IS NULL OR starts_at >= :start)
                  AND (:end IS NULL OR starts_at < :end)
                ORDER BY starts_at DESC, id DESC LIMIT :limit OFFSET :offset''',
                dict(student_id=student_id, start=start_text, end=end_text,
                     limit=limit, offset=offset)).fetchall()
            return [Counseling.model_validate(dict(row)) for row in rows]

    def update(self, counseling_id: int, counseling: CounselingInput) -> Counseling:
        """상담 입력 전체를 교체하고 생성 시각과 ID는 보존한다."""
        data = values(CounselingInput.model_validate(counseling.model_dump(include=set(CounselingInput.model_fields))))
        data.update(id=counseling_id, updated_at=now_text())
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                '''UPDATE counseling SET student_id=:student_id, starts_at=:starts_at,
                duration_minutes=:duration_minutes, category=:category, status=:status,
                title=:title, content_markdown=:content_markdown, follow_up=:follow_up,
                updated_at=:updated_at WHERE id=:id''', data)
            if cursor.rowcount == 0:
                raise NotFoundError('상담 기록을 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (counseling_id,)).fetchone()
            return Counseling.model_validate(dict(row))

    def delete(self, counseling_id: int) -> None:
        """해당 상담만 삭제한다. UI에서는 명시적인 삭제 확인 후 호출한다."""
        with self.database.session(write=True) as connection:
            if connection.execute('DELETE FROM counseling WHERE id=?', (counseling_id,)).rowcount == 0:
                raise NotFoundError('상담 기록을 찾을 수 없습니다.')
