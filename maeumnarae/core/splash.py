"""Windows 배포 스플래시 수명 관리. 일반 Python 실행에서는 아무것도 하지 않는다."""

import atexit
import logging
import os
import sys
from threading import Lock

_lock = Lock()
_closed = False


def close_splash() -> None:
    """부모 프로세스에서만 닫는다. 이벤트 중복 및 종료 경합에도 안전하다."""
    global _closed
    if not getattr(sys, 'frozen', False) or os.environ.get('_PYI_SPLASH_IPC', '0') == '0':
        return
    with _lock:
        if _closed:
            return
        try:
            import pyi_splash

            pyi_splash.close()
        except (ImportError, OSError, RuntimeError):
            logging.getLogger('nicegui').warning('시작 스플래시를 닫지 못했습니다.', exc_info=True)
        else:
            _closed = True


def configure_splash() -> None:
    """초기 import 실패도 정리하고, 브라우저/도움말 모드는 즉시 닫는다."""
    atexit.register(close_splash)
    if any(arg in sys.argv[1:] for arg in ('--browser', '--help', '-h')):
        close_splash()
