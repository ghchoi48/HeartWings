"""SQLCipher 연결, 트랜잭션 및 스키마 관리. 평문 SQLite 대체는 금지한다."""

import os
import hmac
import sys
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary
from maeumnarae.core.models import SchoolSettings, current_school_year

SCHEMA_VERSION = 1
WIDGET_SCHEMA = """CREATE TABLE IF NOT EXISTS home_widget_state (
    id INTEGER PRIMARY KEY CHECK(id = 1), payload TEXT NOT NULL
)"""


def validate_new_password(password: str) -> None:
    if len(password) < 4 or '\x00' in password:
        raise ValueError('새 비밀번호는 4글자 이상이며 NUL 문자를 포함할 수 없습니다.')


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


# 신규 DB는 현재 구조를 버전 1로 직접 생성한다.
SCHEMA = (
    WIDGET_SCHEMA,
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
        updated_at TEXT NOT NULL,
        content_format TEXT NOT NULL DEFAULT 'markdown',
        counseling_method TEXT NOT NULL DEFAULT '',
        counseling_target TEXT NOT NULL DEFAULT '',
        counseling_area TEXT NOT NULL DEFAULT '',
        case_id INTEGER REFERENCES counseling_cases(id) ON DELETE RESTRICT,
        author TEXT NOT NULL DEFAULT '',
        private_note_html TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE counseling_cases (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        report_html TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        intake_html TEXT NOT NULL DEFAULT '',
        closing_html TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE counseling_groups (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0),
        facilitator TEXT NOT NULL,
        participants TEXT NOT NULL,
        purpose TEXT NOT NULL,
        notes TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        period TEXT NOT NULL DEFAULT '',
        counseling_area TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE group_counseling_logs (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL REFERENCES counseling_groups(id) ON DELETE RESTRICT,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
        content_html TEXT NOT NULL,
        follow_up TEXT NOT NULL,
        attendance TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('scheduled', 'completed', 'cancelled'))
    )""",
    """CREATE TABLE group_counseling_members (
        group_id INTEGER NOT NULL REFERENCES counseling_groups(id) ON DELETE CASCADE,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        author TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (group_id, student_id)
    )""",
    """CREATE TABLE teachers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0),
        contact TEXT NOT NULL DEFAULT '',
        extension TEXT NOT NULL DEFAULT '',
        responsibilities TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE consultations (
        id INTEGER PRIMARY KEY,
        teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
        status TEXT NOT NULL CHECK(status IN ('scheduled', 'completed', 'cancelled')),
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        content_html TEXT NOT NULL DEFAULT '',
        follow_up TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        consultation_area TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE "special_educations" (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        law TEXT NOT NULL CHECK(law IN ('학교폭력예방법', '교원지위법')),
        case_number TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        UNIQUE(id, student_id)
    )""",
    """CREATE TABLE special_education_logs (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        case_id INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 1440),
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        title TEXT NOT NULL,
        content_markdown TEXT NOT NULL,
        content_format TEXT NOT NULL,
        counseling_method TEXT NOT NULL,
        counseling_target TEXT NOT NULL,
        counseling_area TEXT NOT NULL,
        follow_up TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(case_id, student_id) REFERENCES special_educations(id, student_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE psychological_tests (
        id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        title TEXT NOT NULL,
        test_date TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '학생' CHECK(target IN ('학생', '보호자(학부모)')),
        test_time TEXT NOT NULL DEFAULT '',
        duration_minutes INTEGER CHECK(duration_minutes BETWEEN 1 AND 1440),
        content_format TEXT NOT NULL DEFAULT 'text' CHECK(content_format IN ('text', 'html')),
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE "education_events" (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        category TEXT NOT NULL CHECK(category IN ('교육', '행사', '단체심리검사')),
        event_date TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        audience TEXT NOT NULL DEFAULT '',
        facilitator TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        event_time TEXT NOT NULL DEFAULT '',
        duration_minutes INTEGER CHECK(duration_minutes BETWEEN 1 AND 1440),
        content_format TEXT NOT NULL DEFAULT 'text' CHECK(content_format IN ('text', 'html')),
        author TEXT NOT NULL DEFAULT '',
        participant_count INTEGER CHECK(participant_count >= 0 AND participant_count <= 2147483647)
    )""",
    """CREATE TABLE calendars (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0),
        color TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('counseling', 'custom')),
        visible INTEGER NOT NULL DEFAULT 1 CHECK(visible IN (0, 1)),
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE calendar_preferences (
        name TEXT PRIMARY KEY,
        visible INTEGER NOT NULL CHECK(visible IN (0, 1)),
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE school_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        school_name TEXT NOT NULL DEFAULT '',
        school_level TEXT NOT NULL DEFAULT '중학교' CHECK(school_level IN ('초등학교', '중학교', '고등학교', 'Wee센터')),
        counselor_name TEXT NOT NULL DEFAULT '',
        office_number TEXT NOT NULL DEFAULT '',
        neis_office_code TEXT NOT NULL DEFAULT '',
        neis_school_code TEXT NOT NULL DEFAULT '',
        neis_api_key TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE home_preferences (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        layout TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE home_todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 300),
        done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1)),
        author TEXT NOT NULL DEFAULT ''
    )""",
    f"""CREATE TABLE "students" (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK(length(trim(name)) > 0),
        student_number TEXT,
        grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
        classroom TEXT NOT NULL,
        birth_date TEXT,
        guardian_contact TEXT NOT NULL,
        notes TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        family_type TEXT NOT NULL DEFAULT '',
        family_welfare_type TEXT NOT NULL DEFAULT '',
        family_members TEXT NOT NULL DEFAULT '[]',
        author TEXT NOT NULL DEFAULT '',
        nickname TEXT NOT NULL DEFAULT '',
        student_contact TEXT NOT NULL DEFAULT '',
        school_year INTEGER NOT NULL DEFAULT {current_school_year()},
        gender TEXT CHECK(gender IN ('남', '여', '기타'))
    )""",
    """CREATE TABLE student_enrollments (
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        school_year INTEGER NOT NULL CHECK(school_year BETWEEN 1900 AND 9999),
        grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
        classroom TEXT NOT NULL CHECK(length(trim(classroom)) > 0),
        student_number TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(student_id, school_year),
        UNIQUE(school_year, grade, classroom, student_number)
    )""",
    """CREATE TABLE "calendar_events" (
        id INTEGER PRIMARY KEY,
        calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE RESTRICT,
        title TEXT NOT NULL CHECK(length(trim(title)) > 0),
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN (0, 1))
    )""",
    """CREATE TABLE journal_attachments (
        id INTEGER PRIMARY KEY,
        counseling_id INTEGER REFERENCES counseling(id) ON DELETE CASCADE,
        group_log_id INTEGER REFERENCES group_counseling_logs(id) ON DELETE CASCADE,
        special_log_id INTEGER REFERENCES special_education_logs(id) ON DELETE CASCADE,
        consultation_id INTEGER REFERENCES consultations(id) ON DELETE CASCADE,
        test_id INTEGER REFERENCES psychological_tests(id) ON DELETE CASCADE,
        education_id INTEGER REFERENCES education_events(id) ON DELETE CASCADE,
        filename TEXT NOT NULL CHECK(length(filename) BETWEEN 1 AND 255),
        content BLOB NOT NULL CHECK(length(content) <= 20971520),
        created_at TEXT NOT NULL,
        CHECK((counseling_id IS NOT NULL) + (group_log_id IS NOT NULL) + (special_log_id IS NOT NULL) + (consultation_id IS NOT NULL) + (test_id IS NOT NULL) + (education_id IS NOT NULL) = 1)
    )""",
    """CREATE INDEX counseling_student_time ON counseling(student_id, starts_at)""",
    """CREATE INDEX counseling_time ON counseling(starts_at)""",
    """CREATE INDEX cases_student ON counseling_cases(student_id, id)""",
    """CREATE INDEX counseling_case_time ON counseling(case_id, starts_at)""",
    """CREATE INDEX group_logs_time ON group_counseling_logs(group_id, starts_at)""",
    """CREATE INDEX group_members_student ON group_counseling_members(student_id, group_id)""",
    """CREATE INDEX teachers_name ON teachers(name)""",
    """CREATE INDEX consultations_teacher_time ON consultations(teacher_id, starts_at)""",
    """CREATE INDEX special_education_student ON special_educations(student_id)""",
    """CREATE INDEX special_education_logs_time ON special_education_logs(case_id, starts_at)""",
    """CREATE INDEX psychological_tests_student_date ON psychological_tests(student_id, test_date)""",
    """CREATE INDEX students_name ON students(name)""",
    """CREATE INDEX calendar_events_time ON calendar_events(calendar_id, starts_at)""",
    """CREATE INDEX attachments_counseling_id ON journal_attachments(counseling_id)""",
    """CREATE INDEX attachments_group_log_id ON journal_attachments(group_log_id)""",
    """CREATE INDEX attachments_special_log_id ON journal_attachments(special_log_id)""",
    """CREATE INDEX attachments_consultation_id ON journal_attachments(consultation_id)""",
    """CREATE INDEX attachments_test_id ON journal_attachments(test_id)""",
    """CREATE INDEX attachments_education_id ON journal_attachments(education_id)""",
    """CREATE TRIGGER counseling_case_insert
    BEFORE INSERT ON counseling
    WHEN NEW.case_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM counseling_cases WHERE id=NEW.case_id AND student_id=NEW.student_id)
    BEGIN SELECT RAISE(ABORT, 'Invalid counseling case'); END""",
    """CREATE TRIGGER counseling_case_update
    BEFORE UPDATE ON counseling
    WHEN NEW.case_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM counseling_cases WHERE id=NEW.case_id AND student_id=NEW.student_id)
    BEGIN SELECT RAISE(ABORT, 'Invalid counseling case'); END""",
    """CREATE TRIGGER case_student_update BEFORE UPDATE OF student_id ON counseling_cases
    WHEN NEW.student_id != OLD.student_id
    BEGIN SELECT RAISE(ABORT, 'Case student cannot change'); END""",
    """CREATE TRIGGER "counseling_snapshot_author"
    AFTER INSERT ON "counseling"
    BEGIN
        UPDATE "counseling" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "counseling_cases_snapshot_author"
    AFTER INSERT ON "counseling_cases"
    BEGIN
        UPDATE "counseling_cases" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "counseling_groups_snapshot_author"
    AFTER INSERT ON "counseling_groups"
    BEGIN
        UPDATE "counseling_groups" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "group_counseling_logs_snapshot_author"
    AFTER INSERT ON "group_counseling_logs"
    BEGIN
        UPDATE "group_counseling_logs" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "group_counseling_members_snapshot_author"
    AFTER INSERT ON "group_counseling_members"
    BEGIN
        UPDATE "group_counseling_members" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "teachers_snapshot_author"
    AFTER INSERT ON "teachers"
    BEGIN
        UPDATE "teachers" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "consultations_snapshot_author"
    AFTER INSERT ON "consultations"
    BEGIN
        UPDATE "consultations" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "special_educations_snapshot_author"
    AFTER INSERT ON "special_educations"
    BEGIN
        UPDATE "special_educations" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "special_education_logs_snapshot_author"
    AFTER INSERT ON "special_education_logs"
    BEGIN
        UPDATE "special_education_logs" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "psychological_tests_snapshot_author"
    AFTER INSERT ON "psychological_tests"
    BEGIN
        UPDATE "psychological_tests" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "education_events_snapshot_author"
    AFTER INSERT ON "education_events"
    BEGIN
        UPDATE "education_events" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "calendars_snapshot_author"
    AFTER INSERT ON "calendars"
    BEGIN
        UPDATE "calendars" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "calendar_preferences_snapshot_author"
    AFTER INSERT ON "calendar_preferences"
    BEGIN
        UPDATE "calendar_preferences" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "school_settings_snapshot_author"
    AFTER INSERT ON "school_settings"
    BEGIN
        UPDATE "school_settings" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "home_preferences_snapshot_author"
    AFTER INSERT ON "home_preferences"
    BEGIN
        UPDATE "home_preferences" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "home_todos_snapshot_author"
    AFTER INSERT ON "home_todos"
    BEGIN
        UPDATE "home_todos" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER "students_snapshot_author"
    AFTER INSERT ON "students"
    BEGIN
        UPDATE "students" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
    """CREATE TRIGGER student_enrollments_snapshot_author
    AFTER INSERT ON student_enrollments BEGIN
        UPDATE student_enrollments SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE student_id=NEW.student_id AND school_year=NEW.school_year;
    END""",
    """CREATE TRIGGER "calendar_events_snapshot_author"
    AFTER INSERT ON "calendar_events"
    BEGIN
        UPDATE "calendar_events" SET author=COALESCE(
            (SELECT counselor_name FROM school_settings WHERE id=1), '')
        WHERE rowid=NEW.rowid;
    END""",
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
        self.write_revision = 0
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
        validate_new_password(new_password)
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
    def _transaction(self, *, write: bool = False):
        """잠금으로 보호된 세션 내부에서만 사용한다."""
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
            if write and connection.total_changes:
                self.write_revision += 1
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

    def initialize(self, school: SchoolSettings | None = None, *, onboarding: bool = False) -> None:
        """버전 1 구조를 생성하고 출석 저장 및 Wee센터 지원을 보완한다."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            validate_new_password(self._password or '')
        with self._session_lock, self._transaction(write=True) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == SCHEMA_VERSION:
                connection.execute(WIDGET_SCHEMA)
                columns = {row['name'] for row in connection.execute('PRAGMA table_info(group_counseling_logs)')}
                if columns and 'attendance' not in columns:
                    connection.execute("ALTER TABLE group_counseling_logs ADD COLUMN attendance TEXT NOT NULL DEFAULT '[]'")
                school_schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='school_settings'"
                ).fetchone()
                if school_schema and 'Wee센터' not in school_schema[0]:
                    # CHECK 제약을 확장하되 설정값과 최초 작성자 스냅샷은 그대로 보존한다.
                    connection.execute('CREATE TEMP TABLE school_settings_copy AS SELECT * FROM school_settings')
                    connection.execute('DROP TABLE school_settings')
                    connection.execute(next(sql for sql in SCHEMA if sql.startswith('CREATE TABLE school_settings (')))
                    connection.execute('INSERT INTO school_settings SELECT * FROM school_settings_copy')
                    connection.execute('DROP TABLE school_settings_copy')
                    connection.execute(next(sql for sql in SCHEMA if sql.startswith('CREATE TRIGGER "school_settings_snapshot_author"')))
                return
            if version != 0 or connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone():
                raise DatabaseError('지원하지 않는 DB 버전 또는 구조입니다. 새 DB 파일을 사용하세요.')
            validate_new_password(self._password or '')
            school = SchoolSettings.model_validate(school.model_dump()) if school is not None else SchoolSettings()
            for statement in SCHEMA:
                connection.execute(statement)
            if onboarding:
                connection.execute('CREATE TABLE onboarding_state (id INTEGER PRIMARY KEY CHECK(id=1), step TEXT NOT NULL)')
                connection.execute("INSERT INTO onboarding_state VALUES (1, 'school')")
            # 학교 설정을 먼저 저장하여 기본 레코드에도 작성자 이름을 반영한다.
            connection.execute('''INSERT INTO school_settings
                (id, school_name, school_level, counselor_name, office_number,
                 neis_office_code, neis_school_code, neis_api_key)
                VALUES (1, :school_name, :school_level, :counselor_name, :office_number,
                        :neis_office_code, :neis_school_code, :neis_api_key)''', school.model_dump())
            connection.execute("INSERT INTO calendars (name, color, source) VALUES ('개인 상담', '#0d9488', 'counseling')")
            connection.execute("INSERT INTO calendar_preferences (name, visible) VALUES ('holidays', 1)")
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise DatabaseError('DB 생성 중 연결 관계의 무결성 검사에 실패했습니다.')
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
