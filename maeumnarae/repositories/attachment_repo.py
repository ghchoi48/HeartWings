"""파일 본문을 암호화 DB에 저장하며 일지별 접근 범위를 검증한다."""
from dataclasses import dataclass
import re

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.repositories._support import now_text

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


def attachment_data(filename: str, content: bytes) -> tuple[str, bytes]:
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename.replace('\\', '/').rsplit('/', 1)[-1]).strip()
    if not filename or filename in ('.', '..') or len(filename) > 255:
        raise ValueError('파일 이름은 1~255자로 지정해 주세요.')
    if not isinstance(content, bytes) or len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError('첨부파일은 파일당 20MB까지 저장할 수 있습니다.')
    return filename, content


def insert_attachments(connection, kind, record_id, attachments):
    """일지와 같은 트랜잭션에서 임시 첨부파일을 저장한다."""
    column = OWNERS[kind][1]
    for filename, content in attachments:
        filename, content = attachment_data(filename, content)
        connection.execute(f'''INSERT INTO journal_attachments ({column}, filename, content, created_at)
            VALUES (?, ?, ?, ?)''', (record_id, filename, content, now_text()))


class DraftAttachments:
    """새 일지의 파일은 메모리에만 보관하고, 저장 후에는 해당 일지에 접근한다."""

    def __init__(self, database, kind, record_id=None):
        self.database, self.kind, self.record_id = database, kind, record_id
        self.files = {}
        self.next_id = 0
        self.closed = False

    @property
    def pending(self):
        return bool(self.files)

    def list(self):
        if self.record_id is not None:
            return AttachmentRepository(self.database, self.kind, self.record_id).list()
        return [Attachment(key, name, len(content), '') for key, (name, content) in self.files.items()]

    def add(self, filename, content):
        if self.closed:
            raise ValueError('닫힌 일지에는 파일을 첨부할 수 없습니다.')
        filename, content = attachment_data(filename, content)
        if self.record_id is not None:
            return AttachmentRepository(self.database, self.kind, self.record_id).add(filename, content)
        self.next_id += 1
        self.files[self.next_id] = (filename, content)

    def download(self, attachment_id):
        if self.record_id is not None:
            return AttachmentRepository(self.database, self.kind, self.record_id).download(attachment_id)
        if attachment_id not in self.files:
            raise NotFoundError('이 일지의 첨부파일을 찾을 수 없습니다.')
        return self.files[attachment_id]

    def delete(self, attachment_id):
        if self.record_id is not None:
            return AttachmentRepository(self.database, self.kind, self.record_id).delete(attachment_id)
        self.download(attachment_id)
        del self.files[attachment_id]

    def discard(self):
        self.closed = True
        self.files.clear()


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
        with self.database.session(write=True) as connection:
            self._require_owner(connection)
            filename, content = attachment_data(filename, content)
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
