"""상담 일정/마크다운 일지 CRUD와 타임라인/캘린더용 기간 조회."""

from datetime import datetime

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import Counseling, CounselingInput, StudentTimelineEntry
from maeumnarae.repositories._support import check_page, now_text, utc_text, values


class CounselingRepository:
    """SQLCipher 연결을 주입받아 상담 데이터를 관리한다."""

    def __init__(self, database: Database):
        self.database = database

    def count(self, *, student_id: int, case_id: int) -> int:
        with self.database.session() as connection:
            return connection.execute('SELECT COUNT(*) FROM counseling WHERE student_id=? AND case_id=?',
                                      (student_id, case_id)).fetchone()[0]

    def create(self, counseling: CounselingInput) -> Counseling:
        """존재하는 학생의 상담을 추가한다. 마크다운 원문을 보존한다."""
        data = values(CounselingInput.model_validate(counseling.model_dump(include=set(CounselingInput.model_fields))))
        data['created_at'] = data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if data['case_id'] is None:
                row = connection.execute('SELECT id FROM counseling_cases WHERE student_id=? ORDER BY id LIMIT 1',
                                         (data['student_id'],)).fetchone()
                if row is None:
                    cursor = connection.execute(
                        "INSERT INTO counseling_cases (student_id, title, created_at, updated_at) VALUES (?, '기본 상담 사례', ?, ?)",
                        (data['student_id'], data['created_at'], data['updated_at']))
                    data['case_id'] = cursor.lastrowid
                else:
                    data['case_id'] = row['id']
            cursor = connection.execute(
                '''INSERT INTO counseling
                (student_id, case_id, starts_at, duration_minutes, category, status, title,
                 content_markdown, content_format, counseling_method, counseling_target, counseling_area, follow_up, private_note_html, created_at, updated_at)
                VALUES (:student_id, :case_id, :starts_at, :duration_minutes, :category, :status, :title,
                        :content_markdown, :content_format, :counseling_method, :counseling_target, :counseling_area,
                        :follow_up, :private_note_html, :created_at, :updated_at)''', data)
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (cursor.lastrowid,)).fetchone()
            return Counseling.model_validate(dict(row))

    def get(self, counseling_id: int) -> Counseling | None:
        """ID로 조회하며 없으면 None을 반환한다."""
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (counseling_id,)).fetchone()
            return Counseling.model_validate(dict(row)) if row else None

    def list(self, *, student_id: int | None = None, start: datetime | None = None,
             end: datetime | None = None, case_id: int | None = None, limit: int = 100, offset: int = 0) -> list[Counseling]:
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
                  AND (:case_id IS NULL OR case_id=:case_id)
                  AND (:start IS NULL OR starts_at >= :start)
                  AND (:end IS NULL OR starts_at < :end)
                ORDER BY starts_at DESC, id DESC LIMIT :limit OFFSET :offset''',
                dict(student_id=student_id, case_id=case_id, start=start_text, end=end_text,
                     limit=limit, offset=offset)).fetchall()
            return [Counseling.model_validate(dict(row)) for row in rows]

    def update(self, counseling_id: int, counseling: CounselingInput) -> Counseling:
        """상담 입력 전체를 교체하고 생성 시각과 ID는 보존한다."""
        data = values(CounselingInput.model_validate(counseling.model_dump(include=set(CounselingInput.model_fields))))
        data.update(id=counseling_id, updated_at=now_text())
        with self.database.session(write=True) as connection:
            cursor = connection.execute(
                '''UPDATE counseling SET student_id=:student_id, case_id=coalesce(:case_id, case_id), starts_at=:starts_at,
                duration_minutes=:duration_minutes, category=:category, status=:status,
                title=:title, content_markdown=:content_markdown, content_format=:content_format, follow_up=:follow_up,
                counseling_method=:counseling_method, counseling_target=:counseling_target, counseling_area=:counseling_area,
                private_note_html=:private_note_html, updated_at=:updated_at WHERE id=:id''', data)
            if cursor.rowcount == 0:
                raise NotFoundError('상담 기록을 찾을 수 없습니다.')
            row = connection.execute('SELECT * FROM counseling WHERE id=?', (counseling_id,)).fetchone()
            return Counseling.model_validate(dict(row))

    def delete(self, counseling_id: int) -> None:
        """해당 상담만 삭제한다. UI에서는 명시적인 삭제 확인 후 호출한다."""
        with self.database.session(write=True) as connection:
            if connection.execute('DELETE FROM counseling WHERE id=?', (counseling_id,)).rowcount == 0:
                raise NotFoundError('상담 기록을 찾을 수 없습니다.')

    def list_timeline(self, *, student_id: int, limit: int = 100, offset: int = 0) -> list[StudentTimelineEntry]:
        """개인 상담, 현재 참여 집단 일지, 특별교육 일지를 최신순으로 합쳐 페이지를 나눈다."""
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute('''
                SELECT id, 'individual' AS kind, starts_at, duration_minutes, title,
                       '' AS group_name, counseling_area, category, counseling_method, counseling_target,
                       '' AS education_name
                FROM counseling WHERE student_id=:student_id
                UNION ALL
                SELECT l.id, 'group' AS kind, l.starts_at, l.duration_minutes, l.title,
                       g.name AS group_name, '', '집단상담', '', '', ''
                FROM group_counseling_logs l
                JOIN counseling_groups g ON g.id=l.group_id
                JOIN group_counseling_members m ON m.group_id=g.id
                WHERE m.student_id=:student_id
                UNION ALL
                SELECT l.id, 'special_education' AS kind, l.starts_at, l.duration_minutes, l.title,
                       '', '', '특별교육', '', l.counseling_target, e.title
                FROM special_education_logs l
                JOIN special_educations e ON e.id=l.case_id AND e.student_id=l.student_id
                WHERE l.student_id=:student_id
                ORDER BY starts_at DESC, kind ASC, id DESC LIMIT :limit OFFSET :offset
            ''', dict(student_id=student_id, limit=limit, offset=offset)).fetchall()
            return [StudentTimelineEntry.model_validate(dict(row)) for row in rows]
