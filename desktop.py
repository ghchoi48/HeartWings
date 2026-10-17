"""네이티브 창 설정과 운영 로그. DB·화면 비즈니스 로직과 분리한다."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(database_path: Path) -> Path:
    """콘솔 없는 앱에서도 오류 위치를 확인할 수 있도록 회전 로그를 생성한다."""
    folder = database_path.parent / 'logs'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / 'maeumnarae.log'
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    handler.setLevel(logging.WARNING)
    for name in ('nicegui', 'uvicorn.error', 'webview'):
        logging.getLogger(name).addHandler(handler)
    return path


def configure_native() -> None:
    """종료 확인, 로컬 다운로드, 최소 창 크기와 비공개 웹뷰 세션을 설정한다."""
    from nicegui import app
    app.native.window_args.update(min_size=(960, 700), confirm_close=True)
    app.native.settings['ALLOW_DOWNLOADS'] = True
    app.native.start_args.update(private_mode=True, debug=False, localization={
        'global.quitConfirmation': '마음나래를 종료할까요? 저장하지 않은 내용은 사라집니다.',
        'global.ok': '확인', 'global.cancel': '취소',
    })
