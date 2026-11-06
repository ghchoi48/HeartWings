"""두 데이터 영역의 전용 SQLCipher 백업. 외부 SQL 정의는 실행하지 않는다."""

import base64
from contextlib import closing
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4

from maeumnarae.core.database import (Database, DatabaseError, SCHEMA, SCHEMA_VERSION,
                                     GOOGLE_CALENDAR_SCHEMA, LEGACY_IMPORT_SCHEMAS)
from maeumnarae.core.upload_limits import MAX_BACKUP_BYTES
from maeumnarae.repositories.home.home_repo import HomeRepository
from maeumnarae.services.data_management.database_maintenance import _snapshot

KINDS = {'personal': '사용자 개인 데이터', 'counseling_school': '상담 데이터 및 학교 정보'}
PartialBackupKind = Literal['personal', 'counseling_school']
PERSONAL = {'home_preferences', 'home_todos', 'home_widget_state', 'google_calendar_subscriptions'}
PERSONAL_SETTINGS = {'counselor_name', 'neis_api_key'}
ONBOARDING = 'CREATE TABLE onboarding_state (id INTEGER PRIMARY KEY CHECK(id=1), step TEXT NOT NULL)'
OPTIONAL_SCHEMAS = {'onboarding_state': ONBOARDING, **LEGACY_IMPORT_SCHEMAS}
FORMAT = 'maeumnarae-partial-backup'


def _schema():
    # 오직 앱 소유 DDL로 컬럼 목록과 외래 키 순서를 산출한다. 사용자 데이터는 넣지 않는다.
    with closing(sqlite3.connect(':memory:')) as connection:
        for statement in (*SCHEMA, GOOGLE_CALENDAR_SCHEMA, *OPTIONAL_SCHEMAS.values()):
            connection.execute(statement)
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        columns = {name: tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{name}")'))
                   for name in names}
        dependencies = {name: {row[2] for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')}
                        for name in names}
        order = []
        while dependencies:
            ready = sorted(name for name, parents in dependencies.items() if not parents - set(order))
            if not ready:
                raise RuntimeError('백업 스키마의 순환 참조를 처리할 수 없습니다.')
            order.extend(ready)
            for name in ready:
                del dependencies[name]
        return columns, order


COLUMNS, ORDER = _schema()


def partial_backup_filename(kind: PartialBackupKind, when: datetime | None = None) -> str:
    _check_kind(kind)
    label = '개인데이터' if kind == 'personal' else '상담데이터'
    return f'마음나래-{label}-{when or datetime.now():%Y%m%d-%H%M%S}.db'


def _check_kind(kind):
    if kind not in KINDS:
        raise ValueError('지원하지 않는 부분 백업 종류입니다.')


def _tables(kind):
    return (PERSONAL if kind == 'personal' else set(COLUMNS) - PERSONAL) | {
        'school_settings', 'calendars', 'calendar_events'}


def _columns(table, kind):
    if table == 'school_settings':
        return tuple(c for c in COLUMNS[table] if c == 'id' or
                     (c in PERSONAL_SETTINGS) == (kind == 'personal'))
    return COLUMNS[table]


def _check_schema(connection):
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables - set(COLUMNS) or set(COLUMNS) - tables - set(OPTIONAL_SCHEMAS):
        raise DatabaseError('지원하지 않는 DB 구조입니다.')
    for table in tables:
        # ALTER TABLE로 추가한 열은 끝에 위치한다. 추출/복원은 명시한 열 이름을 사용한다.
        if {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')} != set(COLUMNS[table]):
            raise DatabaseError('지원하지 않는 DB 컬럼 구조입니다.')
    if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise DatabaseError('지원하지 않는 DB 버전입니다.')
    return tables


def _where(table, kind):
    operator = '=' if kind == 'personal' else '!='
    if table == 'calendars':
        return f" WHERE source{operator}'custom'"
    if table == 'calendar_events':
        return f" WHERE calendar_id IN (SELECT id FROM calendars WHERE source{operator}'custom')"
    return ''


def _extract(connection, kind):
    tables = _check_schema(connection)
    result = {}
    for table in sorted(_tables(kind)):
        columns = _columns(table, kind)
        names = ','.join(f'"{c}"' for c in columns)
        result[table] = ([list(row) for row in connection.execute(
            f'SELECT {names} FROM "{table}"' + _where(table, kind))] if table in tables else None)
    return result


def _encode(value):
    if isinstance(value, bytes):
        return {'blob': base64.b64encode(value).decode('ascii')}
    raise ValueError('지원하지 않는 백업 값입니다.')


def _decode(value):
    if 'blob' not in value:
        return value
    if set(value) != {'blob'} or not isinstance(value['blob'], str):
        raise ValueError('잘못된 바이너리 값입니다.')
    return base64.b64decode(value['blob'], validate=True)


def _validate(data, kind):
    # 이관 테이블을 포함하지 않던 기존 부분 백업도 복원할 수 있다.
    if isinstance(data, dict) and kind == 'counseling_school':
        for table in LEGACY_IMPORT_SCHEMAS:
            data.setdefault(table, None)
    if not isinstance(data, dict) or set(data) != _tables(kind):
        raise ValueError('잘못된 백업 테이블입니다.')
    for table, rows in data.items():
        if table in OPTIONAL_SCHEMAS and rows is None:
            continue
        if not isinstance(rows, list) or any(not isinstance(row, list) or
                len(row) != len(_columns(table, kind)) or
                any(type(v) not in (str, int, float, bytes, type(None)) or
                    (type(v) is float and not math.isfinite(v)) for v in row) for row in rows):
            raise ValueError('잘못된 백업 행입니다.')
    for table in ('calendars', 'calendar_events'):
        ids = [row[0] for row in data[table]]
        if any(type(value) is not int for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('캘린더 또는 일정 번호가 올바르지 않습니다.')
    school = data['school_settings']
    if len(school) != 1 or school[0][0] != 1:
        raise ValueError('학교 설정이 없습니다.')
    calendars = [dict(zip(COLUMNS['calendars'], row)) for row in data['calendars']]
    ids = {row['id'] for row in calendars}
    if len(ids) != len(calendars) or any((row['source'] == 'custom') != (kind == 'personal') for row in calendars):
        raise ValueError('캘린더 분류가 올바르지 않습니다.')
    if any(dict(zip(COLUMNS['calendar_events'], row))['calendar_id'] not in ids for row in data['calendar_events']):
        raise ValueError('일정의 캘린더가 없습니다.')
    if kind == 'personal':
        if len(data['home_widget_state']) != 1 or data['home_widget_state'][0][0] != 1:
            raise ValueError('위젯 데이터가 없습니다.')
        HomeRepository._validate(json.loads(data['home_widget_state'][0][1]))
        name = dict(zip(_columns('school_settings', kind), school[0]))['counselor_name']
        if not isinstance(name, str) or len(name) > 100 or '\x00' in name:
            raise ValueError('상담교사 이름이 올바르지 않습니다.')


def _insert(connection, table, values):
    columns = tuple(values)
    cursor = connection.execute(f'INSERT INTO "{table}" ({",".join(columns)}) '
                                f'VALUES ({",".join("?" for _ in columns)})', tuple(values.values()))
    if 'author' in values:
        connection.execute(f'UPDATE "{table}" SET author=? WHERE rowid=?',
                           (values['author'], cursor.lastrowid))
    return cursor.lastrowid


def _apply(connection, data, kind):
    selected = _tables(kind)
    next_calendar = connection.execute('SELECT COALESCE(MAX(id),0)+1 FROM calendars').fetchone()[0]
    next_event = connection.execute('SELECT COALESCE(MAX(id),0)+1 FROM calendar_events').fetchone()[0]
    if kind == 'counseling_school':
        for table, statement in OPTIONAL_SCHEMAS.items():
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            if data[table] is not None:
                connection.execute(statement)
    for table in reversed(ORDER):
        if table in selected and table not in {'school_settings', *OPTIONAL_SCHEMAS}:
            connection.execute(f'DELETE FROM "{table}"' + _where(table, kind))
    settings = dict(zip(_columns('school_settings', kind), data['school_settings'][0]))
    settings.pop('id')
    connection.execute('UPDATE school_settings SET ' + ','.join(f'{c}=?' for c in settings) + ' WHERE id=1',
                       tuple(settings.values()))
    calendar_ids = {}
    for table in ORDER:
        if table not in selected or table == 'school_settings' or data[table] is None:
            continue
        for row in data[table]:
            values = dict(zip(_columns(table, kind), row))
            if table == 'calendars':
                calendar_ids[values['id']] = next_calendar
                values['id'] = next_calendar
                next_calendar += 1
            elif table == 'calendar_events':
                values['calendar_id'] = calendar_ids[values['calendar_id']]
                values['id'] = next_event
                next_event += 1
            _insert(connection, table, values)
    if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise DatabaseError('복원 데이터의 연결 관계가 올바르지 않습니다.')


def create_partial_backup(database: Database, kind: PartialBackupKind) -> bytes:
    _check_kind(kind)
    try:
        with database._session_lock:
            HomeRepository(database)._ensure_storage()
            with database.session() as connection:
                data = _extract(connection, kind)
            _validate(data, kind)
            with TemporaryDirectory(prefix='maeumnarae-partial-') as directory:
                path = Path(directory) / 'partial.db'
                backup = Database(database._password, path)
                with backup.session(write=True) as connection:
                    connection.execute('CREATE TABLE partial_backup (format TEXT, version INTEGER, '
                                       'schema_version INTEGER, kind TEXT, created_at TEXT, payload TEXT)')
                    connection.execute('INSERT INTO partial_backup VALUES (?,1,?,?,?,?)',
                                       (FORMAT, SCHEMA_VERSION, kind, datetime.now().astimezone().isoformat(),
                                        json.dumps(data, default=_encode, ensure_ascii=False)))
                os.chmod(path, 0o600)
                content = path.read_bytes()
                if len(content) > MAX_BACKUP_BYTES:
                    raise DatabaseError('부분 백업 파일이 지원 크기 256MB를 초과합니다.')
                return content
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, database.driver.DatabaseError):
        raise DatabaseError('부분 백업을 만들지 못했습니다. 데이터와 저장 공간을 확인하세요.') from None


def restore_partial_backup(database: Database, content: bytes, password: str, kind: PartialBackupKind) -> Path:
    _check_kind(kind)
    if not content or len(content) > MAX_BACKUP_BYTES:
        raise DatabaseError('부분 백업 파일은 비어 있지 않은 256MB 이하의 파일이어야 합니다.')
    try:
        with TemporaryDirectory(prefix='maeumnarae-partial-restore-') as directory:
            path = Path(directory) / 'uploaded.db'
            path.write_bytes(content)
            os.chmod(path, 0o600)
            source = Database(password, path)
            with source.session() as connection:
                connection.execute('PRAGMA query_only=ON')
                objects = [tuple(row) for row in connection.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")]
                if objects != [('table', 'partial_backup')]:
                    raise DatabaseError('전용 부분 백업 파일을 선택해 주세요.')
                if [row[0] for row in connection.execute('PRAGMA integrity_check')] != ['ok']:
                    raise DatabaseError('부분 백업 파일이 손상되었습니다.')
                rows = connection.execute('SELECT format,version,schema_version,kind,created_at,payload FROM partial_backup').fetchall()
                if len(rows) != 1 or tuple(rows[0][:4]) != (FORMAT, 1, SCHEMA_VERSION, kind):
                    raise DatabaseError('백업 종류 또는 버전이 맞지 않습니다.')
                data = json.loads(rows[0][5], object_hook=_decode)
            _validate(data, kind)
            # 업로드 DDL을 실행하지 않고 앱 스키마의 암호화 임시 DB로 제약 조건을 검증한다.
            staging = Database(password, Path(directory) / 'validated.db')
            staging.initialize()
            with staging.session(write=True) as connection:
                _apply(connection, data, kind)
            with database._session_lock:
                with database.session() as connection:
                    _check_schema(connection)
                backups = database.path.parent / 'backups'
                backups.mkdir(mode=0o700, exist_ok=True)
                recovery = backups / f'before-partial-restore-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.db'
                _snapshot(database, recovery)
                with database.session(write=True) as connection:
                    _apply(connection, data, kind)
                database._state.generation += 1
                database._password = None
                return recovery
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError,
            OverflowError, RecursionError, database.driver.DatabaseError):
        raise DatabaseError('부분 백업을 복원하지 못했습니다. 파일, 비밀번호와 저장 공간을 확인하세요.') from None
