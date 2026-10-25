"""집단 상담과 집단별 일지의 조회 및 저장."""

import json

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import GroupCounseling, GroupCounselingInput, GroupLog, GroupLogInput
from maeumnarae.repositories.attachment_repo import insert_attachments
from maeumnarae.repositories._support import check_page, now_text, values


class GroupCounselingRepository:
    def __init__(self, database: Database):
        self.database = database

    def count_logs(self, group_id: int) -> int:
        with self.database.session() as connection:
            return connection.execute('SELECT COUNT(*) FROM group_counseling_logs WHERE group_id=?',
                                      (group_id,)).fetchone()[0]

    @staticmethod
    def _group(connection, row) -> GroupCounseling:
        members = connection.execute('''SELECT s.id, s.name, s.grade, s.classroom, s.student_number
            FROM group_counseling_members m JOIN students s ON s.id=m.student_id
            WHERE m.group_id=? ORDER BY s.grade, s.classroom, s.name, s.id''', (row['id'],)).fetchall()
        return GroupCounseling.model_validate(dict(row) | dict(
            student_ids=[m['id'] for m in members],
            participant_labels=[f"{m['name']} · {m['grade']}학년 {m['classroom']}반 · 번호 {m['student_number'] or '미입력'}" for m in members]))

    def list(self, *, limit: int = 100, offset: int = 0) -> list[GroupCounseling]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute('SELECT * FROM counseling_groups ORDER BY id DESC LIMIT ? OFFSET ?',
                                      (limit, offset)).fetchall()
            return [self._group(connection, row) for row in rows]

    def get(self, group_id: int) -> GroupCounseling | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM counseling_groups WHERE id=?', (group_id,)).fetchone()
            return self._group(connection, row) if row else None

    def save(self, value: GroupCounselingInput, group_id: int | None = None) -> GroupCounseling:
        data = values(GroupCounselingInput.model_validate(value.model_dump(include=set(GroupCounselingInput.model_fields))))
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if group_id is None:
                cursor = connection.execute('''INSERT INTO counseling_groups
                    (name, facilitator, period, counseling_area, participants, purpose, notes, created_at, updated_at)
                    VALUES (:name, :facilitator, :period, :counseling_area, :participants, :purpose, :notes, :updated_at, :updated_at)''', data)
                group_id = cursor.lastrowid
            else:
                data['id'] = group_id
                cursor = connection.execute('''UPDATE counseling_groups SET name=:name, facilitator=:facilitator,
                    period=:period, counseling_area=:counseling_area,
                    participants=:participants, purpose=:purpose, notes=:notes, updated_at=:updated_at WHERE id=:id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('집단 상담을 찾을 수 없습니다.')
            student_ids = sorted(set(value.student_ids))
            if student_ids:
                slots = ','.join('?' for _ in student_ids)
                connection.execute(f'''DELETE FROM group_counseling_members
                    WHERE group_id=? AND student_id NOT IN ({slots})''', (group_id, *student_ids))
            else:
                connection.execute('DELETE FROM group_counseling_members WHERE group_id=?', (group_id,))
            connection.executemany('INSERT OR IGNORE INTO group_counseling_members (group_id, student_id) VALUES (?, ?)',
                                   [(group_id, student_id) for student_id in student_ids])
            row = connection.execute('SELECT * FROM counseling_groups WHERE id=?', (group_id,)).fetchone()
            return self._group(connection, row)

    def list_logs(self, group_id: int, *, limit: int = 20, offset: int = 0) -> list[GroupLog]:
        check_page(limit, offset)
        with self.database.session() as connection:
            rows = connection.execute('''SELECT * FROM group_counseling_logs WHERE group_id=?
                ORDER BY starts_at DESC, id DESC LIMIT ? OFFSET ?''', (group_id, limit, offset)).fetchall()
            return [GroupLog.model_validate(dict(row)) for row in rows]

    def get_log(self, log_id: int) -> GroupLog | None:
        with self.database.session() as connection:
            row = connection.execute('SELECT * FROM group_counseling_logs WHERE id=?', (log_id,)).fetchone()
            return GroupLog.model_validate(dict(row)) if row else None

    def save_log(self, value: GroupLogInput, log_id: int | None = None, *, attachments=()) -> GroupLog:
        data = values(GroupLogInput.model_validate(value.model_dump(include=set(GroupLogInput.model_fields))))
        data['attendance'] = json.dumps(data['attendance'], ensure_ascii=False)
        data['updated_at'] = now_text()
        with self.database.session(write=True) as connection:
            if log_id is None:
                cursor = connection.execute('''INSERT INTO group_counseling_logs
                    (group_id, title, starts_at, duration_minutes, status, content_html, follow_up, attendance, created_at, updated_at)
                    VALUES (:group_id, :title, :starts_at, :duration_minutes, :status, :content_html, :follow_up,
                            :attendance, :updated_at, :updated_at)''', data)
                log_id = cursor.lastrowid
            else:
                data['id'] = log_id
                cursor = connection.execute('''UPDATE group_counseling_logs SET title=:title,
                    starts_at=:starts_at, duration_minutes=:duration_minutes, status=:status, content_html=:content_html,
                    follow_up=:follow_up, attendance=:attendance, updated_at=:updated_at WHERE id=:id AND group_id=:group_id''', data)
                if not cursor.rowcount:
                    raise NotFoundError('이 집단의 상담 일지를 찾을 수 없습니다.')
            insert_attachments(connection, 'group_log', log_id, attachments)
            row = connection.execute('SELECT * FROM group_counseling_logs WHERE id=?', (log_id,)).fetchone()
            return GroupLog.model_validate(dict(row))
