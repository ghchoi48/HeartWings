"""GUI 및 multiprocessing 초기화 전 사용할 표준 출력/오류 파일."""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def log_folders(database_path: Path | None = None) -> tuple[Path, ...]:
    """배포 앱은 실행 파일 옆에 기록하고, 쓰기 불가 시 사용자 경로로 대체한다."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    folders = []
    if getattr(sys, 'frozen', False):
        folders.append(Path(sys.executable).resolve().parent / 'logs')
    elif database_path is not None:
        folders.append(database_path.parent / 'logs')
    folders.extend((base / 'maeumnarae' / 'data' / 'logs',
                    Path(tempfile.gettempdir()) / 'maeumnarae' / 'logs'))
    return tuple(dict.fromkeys(folders))


def configure_startup_output() -> Path | None:
    """콘솔이 없는 프로세스만 연결한다. 자식마다 별도 파일을 사용한다."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    filename = f'startup-{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}.log'
    for folder in log_folders():
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / filename
            stream = path.open('a', encoding='utf-8', buffering=1)
            break
        except OSError:
            continue
    else:
        # 로그 경로가 모두 쓰기 불가여도 라이브러리의 write/flush는 지원한다.
        path = None
        stream = open(os.devnull, 'w', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    stream.write(f'Startup: pid={os.getpid()}, frozen={getattr(sys, "frozen", False)}\n')
    return path
