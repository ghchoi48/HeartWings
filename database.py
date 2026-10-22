"""SQLCipher 연결, 트랜잭션 및 스키마 관리. 평문 SQLite 대체는 금지한다."""

import os
import hmac
import sys
import re
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary
from models import SchoolSettings, current_school_year

SCHEMA_VERSION = 29


class DatabaseError(RuntimeError):
    """UI에서 민감 정보 없이 표시할 수 있는 저장소 오류."""


class DatabaseOpenError(DatabaseError):
    """키 오류, 파일 손상 또는 접근 실패."""


class ConflictError(DatabaseError):
    """학년도·학년·반 안의 중복 번호 또는 참조 무결성 위반."""


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


class _DatabaseState:
    def __init__(self):
        self.lock = RLock()
        self.generation = 0


_states: WeakValueDictionary[str, _DatabaseState] = WeakValueDictionary()
_states_lock = Lock()


class Database:
    """연결마다 키와 외래 키를 설정한다. 비밀번호를 파일이나 로그에 쓰지 않는다."""

    def __init__(self, password: str, path: Path | None = None):
        if not password or '\x00' in password:
            raise ValueError('비밀번호는 비어 있거나 NUL 문자를 포함할 수 없습니다.')
        self.path = Path(path) if path is not None else default_database_path()
        self._password = password
        with _states_lock:
            key = os.path.normcase(str(self.path.resolve()))
            self._state = _states.setdefault(key, _DatabaseState())
        self._session_lock = self._state.lock
        self._generation = self._state.generation
        self.student_revision = 0
        try:
            # OS/CPU/Python 버전에 맞는 SQLCipher 확장 모듈이 필요하다.
            self.driver = import_module('sqlcipher3.dbapi2')
        except (ImportError, OSError):
            raise DatabaseError('SQLCipher 드라이버를 불러올 수 없습니다. 설치 안내를 확인하세요.') from None

    def _connect(self):
        """키 적용 직후 실제 페이지 읽기로 암호와 암호화 지원을 확인한다."""
        if self._password is None or self._generation != self._state.generation:
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

    def change_password(self, current_password: str, new_password: str) -> None:
        """SQLCipher의 자체 rekey 트랜잭션으로 키를 바꾸고 성공 후 메모리 키를 갱신한다."""
        if not new_password or '\x00' in new_password:
            raise ValueError('새 비밀번호는 비어 있거나 NUL 문자를 포함할 수 없습니다.')
        with self._session_lock:
            if self._password is None:
                raise DatabaseOpenError('DB가 잠겨 있습니다. 비밀번호를 입력해 다시 열어 주세요.')
            if not hmac.compare_digest(current_password.encode('utf-8'), self._password.encode('utf-8')):
                raise DatabaseError('현재 비밀번호가 올바르지 않습니다.')
            if current_password == new_password:
                raise ValueError('새 비밀번호는 현재 비밀번호와 다르게 입력해 주세요.')
            connection = self._connect()
            try:
                # 다른 연결의 읽기/쓰기와 충돌하면 rekey 전에 중단한다.
                # EXCLUSIVE 모드는 COMMIT 이후에도 이 연결이 잠금을 유지한다.
                connection.execute('PRAGMA locking_mode = EXCLUSIVE')
                connection.execute('BEGIN EXCLUSIVE')
                connection.commit()
                # rekey는 자체 트랜잭션을 사용하므로 session() 안에서 실행하지 않는다.
                escaped = new_password.replace("'", "''")
                connection.execute("PRAGMA rekey = '" + escaped + "'")
            except self.driver.DatabaseError:
                raise DatabaseError('비밀번호를 변경하지 못했습니다. 잠시 후 다시 시도해 주세요.') from None
            finally:
                connection.close()
            # 일부 드라이버는 rekey 실패를 예외로 전달하지 않는다.
            # 열린 연결의 캐시가 아닌 새 연결로 실제 파일의 키를 확인한다.
            try:
                verification = Database(new_password, self.path)._connect()
                verification.close()
            except DatabaseError:
                try:
                    original = self._connect()
                    original.close()
                except DatabaseError:
                    self._password = None
                    raise DatabaseError('DB 비밀번호 변경 결과를 확인할 수 없습니다. DB를 다시 열어 확인해 주세요.') from None
                raise DatabaseError('비밀번호를 변경하지 못했습니다. 기존 비밀번호가 유지됩니다.') from None
            self._password = new_password

    @contextmanager
    def _transaction(self, *, write: bool = False, migration: bool = False):
        """잠금으로 보호된 세션 내부에서만 사용한다."""
        connection = self._connect()
        try:
            if migration:
                # Parent-table rebuilds must preserve all child records. Check every
                # foreign key before committing; normal sessions keep FK enforcement.
                connection.execute('PRAGMA foreign_keys = OFF')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            if migration and connection.execute('PRAGMA foreign_key_check').fetchone():
                raise DatabaseError('DB 이관 중 연결된 자료의 무결성 검사에 실패했습니다.')
            connection.commit()
        except self.driver.IntegrityError:
            connection.rollback()
            raise ConflictError('같은 학년도·학년·반에 중복 번호가 있거나 연결된 학생/상담 기록 조건에 맞지 않습니다.') from None
        except self.driver.DatabaseError:
            connection.rollback()
            raise DatabaseError('DB 작업에 실패했습니다. 파일 상태 또는 잠금을 확인하세요.') from None
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, school: SchoolSettings | None = None) -> None:
        """원자적으로 최초 스키마를 만든다. 미래 버전 DB의 묵시적 다운그레이드는 막는다."""
        with self._session_lock, self._transaction(write=True, migration=True) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            new_database = version == 0
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
            if version == 13:
                connection.execute('''CREATE TABLE education_events (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    category TEXT NOT NULL CHECK(category IN ('교육', '행사')),
                    event_date TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    audience TEXT NOT NULL DEFAULT '',
                    facilitator TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )''')
                connection.execute('PRAGMA user_version = 14')
                version = 14
            if version == 14:
                connection.execute("ALTER TABLE education_events ADD COLUMN event_time TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE education_events ADD COLUMN duration_minutes INTEGER CHECK(duration_minutes BETWEEN 1 AND 1440)")
                connection.execute('PRAGMA user_version = 15')
                version = 15
            if version == 15:
                connection.execute("ALTER TABLE consultations ADD COLUMN consultation_area TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 16')
                version = 16
            if version == 16:
                # 자식 일지를 보존한 채 부모 테이블의 법령 CHECK 제약을 교체한다.
                log_schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='special_education_logs'"
                ).fetchone()[0]
                connection.execute('CREATE TEMP TABLE education_logs_backup AS SELECT * FROM special_education_logs')
                connection.execute('DROP TABLE special_education_logs')
                connection.execute('''CREATE TABLE special_educations_new (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    law TEXT NOT NULL CHECK(law IN ('학교폭력예방법', '교원지위법')),
                    case_number TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(id, student_id)
                )''')
                connection.execute('''INSERT INTO special_educations_new
                    SELECT id, student_id, title,
                        CASE law WHEN '학교폭력특별법' THEN '학교폭력예방법' ELSE law END,
                        case_number, created_at, updated_at FROM special_educations''')
                connection.execute('DROP TABLE special_educations')
                connection.execute('ALTER TABLE special_educations_new RENAME TO special_educations')
                connection.execute('CREATE INDEX special_education_student ON special_educations(student_id)')
                connection.execute(log_schema)
                connection.execute('INSERT INTO special_education_logs SELECT * FROM education_logs_backup')
                connection.execute('DROP TABLE education_logs_backup')
                connection.execute('CREATE INDEX special_education_logs_time ON special_education_logs(case_id, starts_at)')
                connection.execute('PRAGMA user_version = 17')
                version = 17
            if version == 17:
                connection.execute('''CREATE TABLE IF NOT EXISTS psychological_tests (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL,
                    test_date TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )''')
                connection.execute('CREATE INDEX IF NOT EXISTS psychological_tests_student_date ON psychological_tests(student_id, test_date)')
                connection.execute('PRAGMA user_version = 18')
                version = 18
            if version == 18:
                connection.execute('''CREATE TABLE education_events_new (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    category TEXT NOT NULL CHECK(category IN ('교육', '행사', '단체심리검사')),
                    event_date TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    audience TEXT NOT NULL DEFAULT '',
                    facilitator TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    event_time TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER CHECK(duration_minutes BETWEEN 1 AND 1440)
                )''')
                connection.execute('''INSERT INTO education_events_new
                    (id, title, category, event_date, location, audience, facilitator, content,
                     created_at, updated_at, event_time, duration_minutes)
                    SELECT id, title, category, event_date, location, audience, facilitator, content,
                           created_at, updated_at, event_time, duration_minutes FROM education_events''')
                connection.execute('DROP TABLE education_events')
                connection.execute('ALTER TABLE education_events_new RENAME TO education_events')
                connection.execute('PRAGMA user_version = 19')
                version = 19
            if version == 19:
                columns = {row['name'] for row in connection.execute('PRAGMA table_info(psychological_tests)')}
                if 'target' not in columns:
                    connection.execute("ALTER TABLE psychological_tests ADD COLUMN target TEXT NOT NULL DEFAULT '학생' CHECK(target IN ('학생', '보호자(학부모)'))")
                if 'test_time' not in columns:
                    connection.execute("ALTER TABLE psychological_tests ADD COLUMN test_time TEXT NOT NULL DEFAULT ''")
                if 'duration_minutes' not in columns:
                    connection.execute('ALTER TABLE psychological_tests ADD COLUMN duration_minutes INTEGER CHECK(duration_minutes BETWEEN 1 AND 1440)')
                connection.execute('PRAGMA user_version = 20')
                version = 20
            if version == 20:
                for table in ('education_events', 'psychological_tests'):
                    columns = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}
                    if 'content_format' not in columns:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN content_format TEXT NOT NULL DEFAULT 'text' CHECK(content_format IN ('text', 'html'))")
                connection.execute('PRAGMA user_version = 21')
                version = 21
            if version == 21:
                connection.execute("""CREATE TABLE IF NOT EXISTS calendars (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    color TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('counseling', 'custom')),
                    visible INTEGER NOT NULL DEFAULT 1 CHECK(visible IN (0, 1))
                )""")
                connection.execute("""INSERT INTO calendars (name, color, source)
                    SELECT '개인 상담', '#0d9488', 'counseling'
                    WHERE NOT EXISTS (SELECT 1 FROM calendars WHERE source='counseling')""")
                connection.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY,
                    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    starts_at TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
                    status TEXT NOT NULL CHECK(status IN ('scheduled', 'completed', 'cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")
                connection.execute('CREATE INDEX IF NOT EXISTS calendar_events_time ON calendar_events(calendar_id, starts_at)')
                connection.execute('PRAGMA user_version = 22')
                version = 22
            if version == 22:
                connection.execute("""CREATE TABLE IF NOT EXISTS calendar_preferences (
                    name TEXT PRIMARY KEY,
                    visible INTEGER NOT NULL CHECK(visible IN (0, 1))
                )""")
                connection.execute("INSERT OR IGNORE INTO calendar_preferences (name, visible) VALUES ('holidays', 1)")
                connection.execute('PRAGMA user_version = 23')
                version = 23
            if version == 23:
                connection.execute("""CREATE TABLE IF NOT EXISTS school_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    school_name TEXT NOT NULL DEFAULT '',
                    school_level TEXT NOT NULL DEFAULT '중학교'
                        CHECK(school_level IN ('초등학교', '중학교', '고등학교')),
                    counselor_name TEXT NOT NULL DEFAULT '',
                    office_number TEXT NOT NULL DEFAULT ''
                )""")
                connection.execute('INSERT OR IGNORE INTO school_settings (id) VALUES (1)')
                connection.execute('PRAGMA user_version = 24')
                version = 24
            if version == 24:
                connection.execute("""CREATE TABLE IF NOT EXISTS home_preferences (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    layout TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS home_todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 300),
                    done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1))
                )""")
                connection.execute('PRAGMA user_version = 25')
                version = 25
            if version == 25:
                columns = {row[1] for row in connection.execute('PRAGMA table_info(school_settings)')}
                for column in ('neis_office_code', 'neis_school_code', 'neis_api_key'):
                    if column not in columns:
                        connection.execute(f"ALTER TABLE school_settings ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 26')
                version = 26
            if version not in (26, 27, 28, SCHEMA_VERSION):
                raise DatabaseError('지원하지 않는 DB 버전입니다. 앱 버전을 확인하세요.')
            if new_database and school is not None:
                school = SchoolSettings.model_validate(school.model_dump())
                connection.execute('''UPDATE school_settings SET school_name=:school_name,
                    school_level=:school_level, counselor_name=:counselor_name,
                    office_number=:office_number, neis_office_code=:neis_office_code,
                    neis_school_code=:neis_school_code, neis_api_key=:neis_api_key WHERE id=1''', school.model_dump())
            if version == 26:
                # 설정/연결 테이블을 포함한 모든 사용자 테이블에 작성 당시 이름을 보관한다.
                # 내부 테이블(sqlite_sequence 등)은 SQLite가 관리하므로 제외한다.
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                for table in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    columns = {row['name'] for row in connection.execute(f'PRAGMA table_info({quoted})')}
                    if 'author' not in columns:
                        connection.execute(f"ALTER TABLE {quoted} ADD COLUMN author TEXT NOT NULL DEFAULT ''")
                        connection.execute(f'''UPDATE {quoted} SET author=COALESCE(
                            (SELECT counselor_name FROM school_settings WHERE id=1), '')''')
                    trigger = '"' + (table + '_snapshot_author').replace('"', '""') + '"'
                    connection.execute(f'''CREATE TRIGGER IF NOT EXISTS {trigger}
                        AFTER INSERT ON {quoted}
                        BEGIN
                            UPDATE {quoted} SET author=COALESCE(
                                (SELECT counselor_name FROM school_settings WHERE id=1), '')
                            WHERE rowid=NEW.rowid;
                        END''')
                connection.execute('PRAGMA user_version = 27')
                version = 27
            if version == 27:
                columns = {row['name'] for row in connection.execute('PRAGMA table_info(students)')}
                for column in ('nickname', 'student_contact'):
                    if column not in columns:
                        connection.execute(f"ALTER TABLE students ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                connection.execute('PRAGMA user_version = 28')
                version = 28
            if version == 28:
                # Remove the old global number uniqueness: numbers belong to a
                # particular year, grade and classroom, not a student's identity.
                columns = {row['name'] for row in connection.execute('PRAGMA table_info(students)')}
                if 'school_year' not in columns:
                    schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='students'").fetchone()[0]
                    objects = [row[0] for row in connection.execute(
                        "SELECT sql FROM sqlite_master WHERE tbl_name='students' AND type IN ('index','trigger') AND sql IS NOT NULL")]
                    schema = re.sub(r'^CREATE TABLE\s+"?students"?', 'CREATE TABLE students_new', schema, count=1)
                    schema = schema.replace('student_number TEXT UNIQUE', 'student_number TEXT')
                    connection.execute(schema)
                    connection.execute('INSERT INTO students_new SELECT * FROM students')
                    connection.execute('DROP TABLE students')
                    connection.execute('ALTER TABLE students_new RENAME TO students')
                    for statement in objects:
                        connection.execute(statement)
                    year = current_school_year()
                    connection.execute(f'ALTER TABLE students ADD COLUMN school_year INTEGER NOT NULL DEFAULT {year}')
                connection.execute('''CREATE TABLE IF NOT EXISTS student_enrollments (
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    school_year INTEGER NOT NULL CHECK(school_year BETWEEN 1900 AND 9999),
                    grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
                    classroom TEXT NOT NULL CHECK(length(trim(classroom)) > 0),
                    student_number TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(student_id, school_year),
                    UNIQUE(school_year, grade, classroom, student_number)
                )''')
                connection.execute('''INSERT INTO student_enrollments
                    SELECT id, school_year, grade, classroom, student_number, created_at, updated_at, author FROM students WHERE true
                    ON CONFLICT(student_id, school_year) DO NOTHING''')
                connection.execute('''CREATE TRIGGER IF NOT EXISTS student_enrollments_snapshot_author
                    AFTER INSERT ON student_enrollments BEGIN
                        UPDATE student_enrollments SET author=COALESCE(
                            (SELECT counselor_name FROM school_settings WHERE id=1), '')
                        WHERE student_id=NEW.student_id AND school_year=NEW.school_year;
                    END''')
                connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
