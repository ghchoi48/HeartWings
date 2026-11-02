"""암호화 스냅샷 백업과 검증·자동 백업을 거치는 DB 복원."""

import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from maeumnarae.core.upload_limits import MAX_BACKUP_BYTES
from maeumnarae.core.database import Database, DatabaseError, SCHEMA_VERSION


def reset_database(database: Database) -> None:
    """사용 중인 작업을 마친 후 DB를 삭제하고 기존 인스턴스의 접근을 차단한다."""
    with database._session_lock:
        try:
            connection = database._connect()
            try:
                result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if result and result[0] != 0:
                    raise DatabaseError('DB가 사용 중입니다. 다른 창의 작업을 마친 뒤 다시 시도하세요.')
                mode = connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
                if mode.lower() != 'delete':
                    raise DatabaseError('DB가 사용 중이어서 초기화할 수 없습니다.')
            finally:
                connection.close()
            database.path.unlink()
            database._state.generation += 1
            database._password = None
        except (OSError, database.driver.DatabaseError):
            raise DatabaseError('DB를 초기화하지 못했습니다. 파일 사용 상태와 폴더 권한을 확인하세요.') from None


def database_info(database: Database) -> dict:
    with database.session() as connection:
        return {
            'path': str(database.path.resolve()),
            'size': database.path.stat().st_size,
            'schema_version': connection.execute('PRAGMA user_version').fetchone()[0],
            'cipher_version': connection.execute('PRAGMA cipher_version').fetchone()[0],
            'students': connection.execute('SELECT count(*) FROM students').fetchone()[0],
            'counseling': connection.execute('SELECT count(*) FROM counseling').fetchone()[0],
        }


def _verify(database: Database) -> None:
    with database.session() as connection:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version != SCHEMA_VERSION or not {'students', 'counseling'} <= tables:
            raise DatabaseError('지원하는 마음나래 DB 파일이 아닙니다.')
        if [row[0] for row in connection.execute('PRAGMA integrity_check')] != ['ok']:
            raise DatabaseError('DB 파일의 무결성 검사에 실패했습니다.')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise DatabaseError('DB 파일의 데이터 연결 관계에 오류가 있습니다.')


def _snapshot(database: Database, destination: Path) -> None:
    """원본의 WAL 데이터까지 포함한 암호화 스냅샷. destination은 새 파일이어야 한다."""
    source = target = None
    try:
        # 기존 백업이나 현재 DB를 덮어쓰지 않는다.
        with destination.open('xb'):
            pass
    except OSError:
        raise DatabaseError('백업 파일을 만들 수 없습니다. 저장 공간과 폴더 권한을 확인하세요.') from None
    try:
        os.chmod(destination, 0o600)
        source = database._connect()
        snapshot = Database(database._password, destination)
        target = snapshot._connect()
        source.backup(target)
        target.close()
        target = None
        _verify(snapshot)
    except BaseException:
        if target is not None:
            target.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        if source is not None:
            source.close()


def create_backup(database: Database) -> bytes:
    """다운로드용 암호화 DB 파일. 임시 파일은 반환 전에 제거한다."""
    with database._session_lock:
        try:
            with TemporaryDirectory(prefix='maeumnarae-backup-') as directory:
                path = Path(directory) / 'backup.db'
                _snapshot(database, path)
                return path.read_bytes()
        except (OSError, database.driver.DatabaseError):
            raise DatabaseError('DB 백업에 실패했습니다. 저장 공간과 파일 상태를 확인하세요.') from None


def restore_backup(database: Database, content: bytes, password: str) -> Path:
    """복원 후보를 검증하고 자동 백업 후 원자적으로 교체한다."""
    if not content or len(content) > MAX_BACKUP_BYTES:
        raise DatabaseError('복원 파일은 비어 있지 않은 256MB 이하의 DB 파일이어야 합니다.')
    with database._session_lock:
        try:
            # 같은 볼륨에서 os.replace하여 교체 중 부분 파일이 노출되지 않게 한다.
            with TemporaryDirectory(prefix='.restore-', dir=database.path.parent,
                                    ignore_cleanup_errors=True) as directory:
                candidate_path = Path(directory) / 'candidate.db'
                candidate_path.write_bytes(content)
                os.chmod(candidate_path, 0o600)
                candidate = Database(password, candidate_path)
                _verify(candidate)
                candidate.initialize()
                _verify(candidate)
                # 업로드 DB의 journal 설정과 관계없이 단일 파일을 만든다.
                replacement = Path(directory) / 'replacement.db'
                _snapshot(candidate, replacement)
                backups = database.path.parent / 'backups'
                backups.mkdir(mode=0o700, exist_ok=True)
                name = f'before-restore-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.db'
                recovery = backups / name
                _snapshot(database, recovery)
                connection = database._connect()
                try:
                    result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                    if result and result[0] != 0:
                        raise DatabaseError('DB가 사용 중입니다. 다른 창의 작업을 마친 뒤 다시 시도하세요.')
                    mode = connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
                    if mode.lower() != 'delete':
                        raise DatabaseError('DB가 사용 중이어서 복원할 수 없습니다.')
                finally:
                    connection.close()
                os.replace(replacement, database.path)
                database._state.generation += 1
                database._password = None
                return recovery
        except (OSError, database.driver.DatabaseError):
            raise DatabaseError('DB를 복원하지 못했습니다. 저장 공간과 파일 사용 상태를 확인하세요. 기존 DB는 유지됩니다.') from None
