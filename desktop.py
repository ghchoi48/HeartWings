"""네이티브 창 설정과 운영 로그. DB·화면 비즈니스 로직과 분리한다."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ICON_PATH = Path(__file__).resolve().with_name('icon.ico')


def _set_app_icon(window, dark: bool) -> None:
    """웹뷰 자식 프로세스에서 OS의 창/실행 중인 앱 아이콘을 변경한다."""
    path = ICON_PATH.with_name('icon-dark.ico' if dark else 'icon.ico')
    if sys.platform == 'darwin':
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper

        def apply():
            image = NSImage.alloc().initByReferencingFile_(str(path.with_suffix('.png') if dark else path))
            NSApplication.sharedApplication().setApplicationIconImage_(image)
        AppHelper.callAfter(apply)
    elif sys.platform == 'win32':
        from nicegui.native.window_icon import apply_icon
        apply_icon(window.native.Handle.ToInt32(), window.title, str(path))
    elif sys.platform.startswith('linux'):
        from gi.repository import GLib
        GLib.idle_add(window.native.set_icon_from_file, str(path.with_suffix('.png') if dark else path))


def update_native_icon(dark: bool) -> None:
    """브라우저 모드에서는 무시하고 네이티브 창으로만 아이콘 변경을 전달한다."""
    from nicegui.native import native
    if native.method_queue is not None:
        native.method_queue.put(('set_app_icon', (dark,), {}))


# spawn으로 다시 import되는 웹뷰 프로세스에도 동일한 메서드를 등록한다.
# NiceGUI의 WindowProxy에는 아이콘 변경 API가 없어 기존 메서드 큐를 이용한다.
try:
    import webview
except ImportError:
    pass
else:
    webview.Window.set_app_icon = _set_app_icon


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
    app.native.start_args.update(private_mode=True, debug=False, icon=str(ICON_PATH), localization={
        'global.quitConfirmation': '마음나래를 종료할까요? 저장하지 않은 내용은 사라집니다.',
        'global.ok': '확인', 'global.cancel': '취소',
    })
