"""파일 본문을 암호화 DB에 저장하며 일지별 접근 범위를 검증한다."""
from dataclasses import dataclass
import re

from database import Database, NotFoundError
from repositories._support import now_text

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
OWNERS = {
    'counseling': ('counseling', 'counseling_id'),
    'group_log': ('group_counseling_logs', 'group_log_id'),
    'special_log': ('special_education_logs', 'special_log_id'),
    'consultation': ('consultations', 'consultation_id'),
    'test': ('psychological_tests', 'test_id'),
    'education': ('education_events', 'education_id'),
}


@dataclass(frozen=True)
class Attachment:
    id: int
    filename: str
    size: int
    created_at: str


class AttachmentRepository:
    def __init__(self, database: Database, kind: str, record_id: int):
        if kind not in OWNERS or not isinstance(record_id, int) or record_id <= 0:
            raise ValueError('저장된 일지를 선택해 주세요.')
        self.database = database
        self.table, self.column = OWNERS[kind]
        self.record_id = record_id

    def _require_owner(self, connection):
        if connection.execute(f'SELECT 1 FROM {self.table} WHERE id=?', (self.record_id,)).fetchone() is None:
            raise NotFoundError('일지가 삭제되었거나 존재하지 않습니다.')

    def list(self) -> list[Attachment]:
        with self.database.session() as connection:
            self._require_owner(connection)
            return [Attachment(**dict(row)) for row in connection.execute(f'''
                SELECT id, filename, length(content) AS size, created_at FROM journal_attachments
                WHERE {self.column}=? ORDER BY id''', (self.record_id,))]

    def add(self, filename: str, content: bytes) -> None:
        filename = re.sub(r'[\x00-\x1f\x7f]', '', filename.replace('\\', '/').rsplit('/', 1)[-1]).strip()
        if not filename or filename in ('.', '..') or len(filename) > 255:
            raise ValueError('파일 이름은 1~255자로 지정해 주세요.')
        if not isinstance(content, bytes) or len(content) > MAX_ATTACHMENT_BYTES:
            raise ValueError('첨부파일은 파일당 20MB까지 저장할 수 있습니다.')
        with self.database.session(write=True) as connection:
            self._require_owner(connection)
            connection.execute(f'''INSERT INTO journal_attachments ({self.column}, filename, content, created_at)
                VALUES (?, ?, ?, ?)''', (self.record_id, filename, content, now_text()))

    def download(self, attachment_id: int) -> tuple[str, bytes]:
        with self.database.session() as connection:
            row = connection.execute(f'''SELECT filename, content FROM journal_attachments
                WHERE id=? AND {self.column}=?''', (attachment_id, self.record_id)).fetchone()
            if row is None:
                raise NotFoundError('이 일지의 첨부파일을 찾을 수 없습니다.')
            return row['filename'], bytes(row['content'])

    def delete(self, attachment_id: int) -> None:
        with self.database.session(write=True) as connection:
            if not connection.execute(f'DELETE FROM journal_attachments WHERE id=? AND {self.column}=?',
                                      (attachment_id, self.record_id)).rowcount:
                raise NotFoundError('이 일지의 첨부파일을 찾을 수 없습니다.')
