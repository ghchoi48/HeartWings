"""SQLCipher 연결, 트랜잭션 및 스키마 관리. 평문 SQLite 대체는 금지한다."""

import os
import sys
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from threading import RLock


class DatabaseError(RuntimeError):
    """UI에서 민감 정보 없이 표시할 수 있는 저장소 오류."""


class DatabaseOpenError(DatabaseError):
    """키 오류, 파일 손상 또는 접근 실패."""


class ConflictError(DatabaseError):
    """중복 학번 또는 참조 무결성 위반."""


class NotFoundError(DatabaseError):
    """수정/삭제할 레코드가 존재하지 않음."""


def default_database_path() -> Path:
    """실행 파일/임시 압축 해제 위치 대신 사용자별 쓰기 가능한 경로를 쓴다."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / 'maeumnarae' / 'data' / 'maeumnarae.db'


SCHEMA = (
    """CREATE TABLE students (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0),
        student_number TEXT UNIQUE,
        grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
        classroom TEXT NOT NULL,
        birth_date TEXT,
        guardian_contact TEXT NOT NULL,
        notes TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE counseling (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
        category TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('scheduled', 'completed', 'cancelled')),
        title TEXT NOT NULL,
        content_markdown TEXT NOT NULL,
        follow_up TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    'CREATE INDEX counseling_student_time ON counseling(student_id, starts_at)',
    'CREATE INDEX counseling_time ON counseling(starts_at)',
    'CREATE INDEX students_name ON students(name)',
)


class Database:
    """연결마다 키와 외래 키를 설정한다. 비밀번호를 파일이나 로그에 쓰지 않는다."""

    def __init__(self, password: str, path: Path | None = None):
        if not password or '\x00' in password:
            raise ValueError('비밀번호는 비어 있거나 NUL 문자를 포함할 수 없습니다.')
        self.path = Path(path) if path is not None else default_database_path()
        self._password = password
        self._session_lock = RLock()
        self.student_revision = 0
        try:
            # OS/CPU/Python 버전에 맞는 SQLCipher 확장 모듈이 필요하다.
            self.driver = import_module('sqlcipher3.dbapi2')
        except (ImportError, OSError):
            raise DatabaseError('SQLCipher 드라이버를 불러올 수 없습니다. 설치 안내를 확인하세요.') from None

    def _connect(self):
        """키 적용 직후 실제 페이지 읽기로 암호와 암호화 지원을 확인한다."""
        if self._password is None:
            raise DatabaseOpenError('DB가 잠겨 있습니다. 비밀번호를 입력해 다시 열어 주세요.')
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = self.driver.connect(str(self.path), timeout=10, isolation_level=None)
            # PRAGMA는 바인딩을 지원하지 않는다. 작은따옴표를 SQL 리터럴로 escape한다.
            escaped = self._password.replace("'", "''")
            connection.execute("PRAGMA key = '" + escaped + "'")
            version = connection.execute('PRAGMA cipher_version').fetchone()
            if not version or not version[0]:
                raise DatabaseOpenError('SQLCipher 암호화 지원을 확인할 수 없습니다.')
            connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA temp_store = MEMORY')
            connection.row_factory = self.driver.Row
            return connection
        except (self.driver.DatabaseError, OSError):
            if connection is not None:
                connection.close()
            raise DatabaseOpenError('DB를 열 수 없습니다. 비밀번호, 파일 상태와 접근 권한을 확인하세요.') from None
        except Exception:
            if connection is not None:
                connection.close()
            raise

    @contextmanager
    def session(self, *, write: bool = False):
        """작업 단위별 커밋/롤백/종료. 연결을 UI나 스레드 사이에 공유하지 않는다."""
        with self._session_lock:
            with self._transaction(write=write) as connection:
                yield connection

    def lock(self) -> None:
        """진행 중인 트랜잭션 완료 후 키 참조를 해제하고 이후 DB 접근을 차단한다."""
        with self._session_lock:
            self._password = None

    @contextmanager
    def _transaction(self, *, write: bool = False):
        """잠금으로 보호된 세션 내부에서만 사용한다."""
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except self.driver.IntegrityError:
            connection.rollback()
            raise ConflictError('중복 학번이거나 연결된 학생/상담 기록 조건에 맞지 않습니다.') from None
        except self.driver.DatabaseError:
            connection.rollback()
            raise DatabaseError('DB 작업에 실패했습니다. 파일 상태 또는 잠금을 확인하세요.') from None
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """원자적으로 최초 스키마를 만든다. 미래 버전 DB의 묵시적 다운그레이드는 막는다."""
        with self.session(write=True) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.execute('PRAGMA user_version = 1')
                version = 1
            if version == 1:
                connection.execute("ALTER TABLE students ADD COLUMN family_type TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE students ADD COLUMN family_welfare_type TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE students ADD COLUMN family_members TEXT NOT NULL DEFAULT '[]'")
                connection.execute('PRAGMA user_version = 2')
                version = 2
            if version == 2:
                connection.execute("ALTER TABLE counseling ADD COLUMN content_format TEXT NOT NULL DEFAULT 'markdown'")
                connection.execute('PRAGMA user_version = 3')
                version = 3
            if version == 3:
                connection.execute("ALTER TABLE counseling ADD COLUMN counseling_method TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE counseling ADD COLUMN counseling_target TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 4')
                version = 4
            if version == 4:
                connection.execute("ALTER TABLE counseling ADD COLUMN counseling_area TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 5')
                version = 5
            if version == 5:
                connection.execute("""CREATE TABLE counseling_cases (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    report_html TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""")
                connection.execute('CREATE INDEX cases_student ON counseling_cases(student_id, id)')
                connection.execute('ALTER TABLE counseling ADD COLUMN case_id INTEGER REFERENCES counseling_cases(id) ON DELETE RESTRICT')
                connection.execute("""INSERT INTO counseling_cases (student_id, title, created_at, updated_at)
                    SELECT student_id, '기존 상담 사례', min(created_at), max(updated_at)
                    FROM counseling GROUP BY student_id""")
                connection.execute('UPDATE counseling SET case_id=(SELECT id FROM counseling_cases WHERE student_id=counseling.student_id)')
                connection.execute('CREATE INDEX counseling_case_time ON counseling(case_id, starts_at)')
                for event in ('INSERT', 'UPDATE'):
                    connection.execute(f"""CREATE TRIGGER counseling_case_{event.lower()}
                        BEFORE {event} ON counseling
                        WHEN NEW.case_id IS NULL OR NOT EXISTS (
                            SELECT 1 FROM counseling_cases WHERE id=NEW.case_id AND student_id=NEW.student_id)
                        BEGIN SELECT RAISE(ABORT, 'Invalid counseling case'); END""")
                connection.execute("""CREATE TRIGGER case_student_update BEFORE UPDATE OF student_id ON counseling_cases
                    WHEN NEW.student_id != OLD.student_id
                    BEGIN SELECT RAISE(ABORT, 'Case student cannot change'); END""")
                connection.execute('PRAGMA user_version = 6')
                version = 6
            if version == 6:
                connection.execute("ALTER TABLE counseling_cases ADD COLUMN intake_html TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE counseling_cases ADD COLUMN closing_html TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 7')
                version = 7
            if version == 7:
                connection.execute("""CREATE TABLE counseling_groups (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    facilitator TEXT NOT NULL, participants TEXT NOT NULL,
                    purpose TEXT NOT NULL, notes TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE group_counseling_logs (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL REFERENCES counseling_groups(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    starts_at TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
                    content_html TEXT NOT NULL, follow_up TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""")
                connection.execute('CREATE INDEX group_logs_time ON group_counseling_logs(group_id, starts_at)')
                connection.execute('PRAGMA user_version = 8')
                version = 8
            if version == 8:
                connection.execute("""CREATE TABLE group_counseling_members (
                    group_id INTEGER NOT NULL REFERENCES counseling_groups(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
                    PRIMARY KEY (group_id, student_id)
                )""")
                connection.execute('CREATE INDEX group_members_student ON group_counseling_members(student_id, group_id)')
                connection.execute('PRAGMA user_version = 9')
                version = 9
            if version == 9:
                connection.execute("ALTER TABLE counseling_groups ADD COLUMN period TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE counseling_groups ADD COLUMN counseling_area TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 10')
                version = 10
            if version == 10:
                connection.execute('''CREATE TABLE teachers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    contact TEXT NOT NULL DEFAULT '',
                    extension TEXT NOT NULL DEFAULT '',
                    responsibilities TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )''')
                connection.execute('CREATE INDEX teachers_name ON teachers(name)')
                connection.execute('PRAGMA user_version = 11')
                version = 11
            if version == 11:
                connection.execute('''CREATE TABLE consultations (
                    id INTEGER PRIMARY KEY,
                    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
                    starts_at TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
                    status TEXT NOT NULL CHECK(status IN ('scheduled', 'completed', 'cancelled')),
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    content_html TEXT NOT NULL DEFAULT '',
                    follow_up TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )''')
                connection.execute('CREATE INDEX consultations_teacher_time ON consultations(teacher_id, starts_at)')
                connection.execute('PRAGMA user_version = 12')
                version = 12
            if version == 12:
                connection.execute('''CREATE TABLE special_educations (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    law TEXT NOT NULL CHECK(law IN ('학교폭력특별법', '교원지위법')),
                    case_number TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(id, student_id)
                )''')
                connection.execute('''CREATE TABLE special_education_logs (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
                    case_id INTEGER NOT NULL,
                    starts_at TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
                    category TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL,
                    content_markdown TEXT NOT NULL, content_format TEXT NOT NULL,
                    counseling_method TEXT NOT NULL, counseling_target TEXT NOT NULL,
                    counseling_area TEXT NOT NULL, follow_up TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(case_id, student_id) REFERENCES special_educations(id, student_id) ON DELETE RESTRICT
                )''')
                connection.execute('CREATE INDEX special_education_student ON special_educations(student_id)')
                connection.execute('CREATE INDEX special_education_logs_time ON special_education_logs(case_id, starts_at)')
                connection.execute('PRAGMA user_version = 13')
                version = 13
            if version != 13:
                raise DatabaseError('지원하지 않는 DB 버전입니다. 앱 버전을 확인하세요.')
