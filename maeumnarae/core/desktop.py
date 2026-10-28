"""네이티브 창 설정과 운영 로그. DB·화면 비즈니스 로직과 분리한다."""

import asyncio
import logging
import multiprocessing
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock, Timer

from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.core.startup import log_folders
from maeumnarae.core.splash import close_splash

ICON_PATH = RESOURCE_ROOT / 'icons' / 'icon.ico'
NATIVE_START_TIMEOUT = 30.0
NATIVE_SHUTDOWN_GRACE = 5.0
_original_open_window = None


def _exit_after_flush(code: int) -> None:
    """웹뷰의 비데몬 스레드가 남아 있어도 오류 로그를 기록하고 종료한다."""
    try:
        logging.shutdown()
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.flush()
    finally:
        os._exit(code)


def _guarded_open_window(*args, **kwargs) -> None:
    """spawn으로 직렬화할 수 있는 네이티브 자식 프로세스 진입점."""
    from nicegui.native import native_mode

    # frozen 자식은 application.main()을 거치지 않을 수 있다.
    if not logging.getLogger('nicegui').handlers:
        configure_logging(None)
    try:
        original = _original_open_window or native_mode._open_window
        create_window = native_mode.webview.create_window

        def create_fitted_window(*window_args, **window_kwargs):
            state_path = window_kwargs.pop('_maeumnarae_state_path', None)
            window = create_window(*window_args, **window_kwargs)
            if sys.platform == 'win32' and window is not None:
                if state_path:
                    from maeumnarae.core.window_state import install_window_state
                    install_window_state(window, Path(state_path), _fit_window_to_work_area)
                else:
                    window.events.before_show += _fit_window_to_work_area
            return window

        native_mode.webview.create_window = create_fitted_window
        try:
            original(*args, **kwargs)
        finally:
            native_mode.webview.create_window = create_window
    except BaseException:
        logging.getLogger('nicegui').exception('네이티브 창 초기화에 실패했습니다. 창 프로세스를 종료합니다.')
        _exit_after_flush(1)


def _fit_window_to_work_area(window, saved=None) -> None:
    """DPI 적용 후의 창 외곽을 작업 표시줄을 제외한 영역 안에 배치한다."""
    from System.Drawing import Point, Size
    from System.Windows.Forms import FormStartPosition, Screen

    form = window.native
    area = Screen.FromControl(form).WorkingArea
    if saved:
        from System.Drawing import Rectangle
        area = Screen.FromRectangle(Rectangle(saved['x'], saved['y'],
                                              saved['width'], saved['height'])).WorkingArea
    # 작은 화면/높은 배율에서는 최소 크기도 작업 영역보다 작아야 한다.
    form.MinimumSize = Size(min(form.MinimumSize.Width, area.Width),
                            min(form.MinimumSize.Height, area.Height))
    width = min(max(saved['width'], form.MinimumSize.Width), area.Width) if saved else min(form.Width, area.Width)
    height = min(max(saved['height'], form.MinimumSize.Height), area.Height) if saved else min(form.Height, area.Height)
    form.Size = Size(width, height)
    form.StartPosition = FormStartPosition.Manual
    x = min(max(saved['x'], area.X), area.X + area.Width - width) if saved else area.X + (area.Width - width) // 2
    y = min(max(saved['y'], area.Y), area.Y + area.Height - height) if saved else area.Y + (area.Height - height) // 2
    form.Location = Point(x, y)


def register_native_startup_guard() -> None:
    """freeze_support 이전에 설치한다. NiceGUI 내부 진입점 의존은 여기로 한정한다."""
    from nicegui.native import native_mode

    global _original_open_window
    if native_mode._open_window is not _guarded_open_window:
        _original_open_window = native_mode._open_window
        native_mode._open_window = _guarded_open_window


def _force_native_exit() -> None:
    """이 앱의 자식만 정리한다. multiprocessing의 종료 시 join은 기다리지 않는다."""
    logger = logging.getLogger('nicegui')
    logger.error('네이티브 시작 실패 후 종료가 지연되어 서버를 강제 종료합니다.')
    try:
        children = multiprocessing.active_children()
        for child in children:
            try:
                child.terminate()
            except (OSError, ValueError):
                logger.exception('자식 프로세스를 종료하지 못했습니다.')
        for child in children:
            try:
                if child.is_alive():
                    child.kill()
            except (OSError, ValueError):
                logger.exception('자식 프로세스를 강제 종료하지 못했습니다.')
    finally:
        _exit_after_flush(1)


class NativeStartupGuard:
    """shown과 종료 이벤트의 경합을 직렬화하고 이벤트 루프 밖에서 제한 시간을 감시한다."""

    def __init__(self, shutdown) -> None:
        self._shutdown = shutdown
        self._lock = Lock()
        self._state = 'waiting'
        self._timer = None
        self._exit_timer = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._state != 'waiting' or self._timer is not None:
                return
            self._timer = Timer(NATIVE_START_TIMEOUT, self._timeout, args=(loop,))
            self._timer.daemon = True
            self._timer.start()

    def shown(self) -> None:
        self._cancel('shown')
        close_splash()

    def stop(self) -> None:
        self._cancel('stopped')
        close_splash()

    def _cancel(self, state: str) -> None:
        with self._lock:
            if self._state != 'waiting':
                return
            self._state = state
            if self._timer is not None:
                self._timer.cancel()

    def _timeout(self, loop) -> None:
        with self._lock:
            if self._state != 'waiting':
                return
            self._state = 'failed'
            # on_shutdown은 종료 완료가 아니다. 실패 시에는 이 타이머를 유지한다.
            self._exit_timer = Timer(NATIVE_SHUTDOWN_GRACE, _force_native_exit)
            self._exit_timer.daemon = True
            self._exit_timer.start()
        close_splash()
        logging.getLogger('nicegui').error(
            '서버 시작 후 %.0f초 동안 창이 표시되지 않아 서버를 종료합니다.', NATIVE_START_TIMEOUT)
        try:
            loop.call_soon_threadsafe(self._shutdown)
        except RuntimeError:
            # 이미 닫힌 이벤트 루프도 위의 강제 종료 타이머로 정리한다.
            logging.getLogger('nicegui').exception('서버 종료 요청을 전달하지 못했습니다.')


def open_folder(folder: Path) -> None:
    """운영체제의 파일 탐색기로 폴더를 연다."""
    folder = folder.resolve()
    if not folder.is_dir():
        raise FileNotFoundError('폴더를 찾을 수 없습니다.')
    if sys.platform == 'win32':
        os.startfile(str(folder))
    else:
        command = 'open' if sys.platform == 'darwin' else 'xdg-open'
        subprocess.run([command, str(folder)], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _set_app_icon(window, dark: bool) -> None:
    """웹뷰 자식 프로세스에서 OS의 창/실행 중인 앱 아이콘을 변경한다."""
    path = ICON_PATH.with_name('icon-dark.ico' if dark else 'icon.ico')
    if sys.platform == 'darwin':
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper

        def apply():
            image = NSImage.alloc().initByReferencingFile_(str(path.with_suffix('.icns')))
            NSApplication.sharedApplication().setApplicationIconImage_(image)
        AppHelper.callAfter(apply)
    elif sys.platform == 'win32':
        from nicegui.native.window_icon import apply_icon
        apply_icon(window.native.Handle.ToInt32(), window.title, str(path))
    elif sys.platform.startswith('linux'):
        from gi.repository import GLib
        GLib.idle_add(window.native.set_icon_from_file, str(path.with_name(f'{path.stem}-desktop.png')))


def update_native_icon(dark: bool) -> None:
    """브라우저 모드에서는 무시하고 네이티브 창으로만 아이콘 변경을 전달한다."""
    from nicegui.native import native
    if native.method_queue is not None:
        native.method_queue.put(('set_app_icon', (dark,), {}))


def register_native_icon() -> None:
    """freeze_support 이전에 각 프로세스의 Window에 메서드를 등록한다."""
    try:
        import webview
    except ImportError:
        return
    webview.Window.set_app_icon = _set_app_icon


def configure_logging(database_path: Path | None) -> Path:
    """콘솔 없는 앱에서도 오류 위치를 확인할 수 있도록 회전 로그를 생성한다."""
    for folder in log_folders(database_path):
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / 'maeumnarae.log'
            handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding='utf-8')
            break
        except OSError:
            if folder == log_folders(database_path)[-1]:
                raise
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    handler.setLevel(logging.WARNING)
    for name in ('nicegui', 'uvicorn.error', 'webview'):
        logging.getLogger(name).addHandler(handler)
    return path


def configure_native(state_path: Path | None = None) -> None:
    """종료 확인, 로컬 다운로드, 최소 창 크기와 비공개 웹뷰 세션을 설정한다."""
    from nicegui import app
    guard = NativeStartupGuard(app.shutdown)
    app.on_startup(guard.start)
    app.on_shutdown(guard.stop)
    app.native.on('shown', guard.shown)
    app.native.window_args.update(min_size=(960, 700), confirm_close=True)
    if state_path is not None:
        app.native.window_args['_maeumnarae_state_path'] = str(state_path)
    app.native.settings['ALLOW_DOWNLOADS'] = True
    app.native.start_args.update(private_mode=True, debug=False, icon=str(ICON_PATH), localization={
        'global.quitConfirmation': '마음나래를 종료할까요? 저장하지 않은 내용은 사라집니다.',
        'global.ok': '확인', 'global.cancel': '취소',
    })
