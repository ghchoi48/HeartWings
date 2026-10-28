"""실제 GUI 없이 시작 실패, spawn 및 서버 종료 경합을 검증한다."""

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import textwrap
import time
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from maeumnarae.core import desktop


@pytest.mark.parametrize('scale,area', [
    (1, (0, 0, 1920, 1040)),
    (1.25, (0, 0, 1920, 1030)),
    (1.5, (0, 0, 1920, 1020)),
    (2, (0, 0, 1920, 1000)),
    (1.5, (-1920, 60, 1920, 1020)),
    (1, (0, 0, 2560, 1400)),
])
@pytest.mark.parametrize('restore', [False, True])
def test_initial_window_fits_work_area(monkeypatch, scale, area, restore):
    def size(width, height):
        return SimpleNamespace(Width=width, Height=height)

    def point(x, y):
        return SimpleNamespace(X=x, Y=y)

    work_area = SimpleNamespace(X=area[0], Y=area[1], Width=area[2], Height=area[3])
    form = SimpleNamespace(Width=int(1440 * scale), Height=int(1000 * scale),
                           MinimumSize=size(int(960 * scale), int(700 * scale)))
    monkeypatch.setitem(sys.modules, 'System.Drawing', SimpleNamespace(
        Point=point, Size=size, Rectangle=lambda *args: args))
    monkeypatch.setitem(sys.modules, 'System.Windows.Forms', SimpleNamespace(
        FormStartPosition=SimpleNamespace(Manual='manual'),
        Screen=SimpleNamespace(FromControl=lambda control: SimpleNamespace(WorkingArea=work_area),
                               FromRectangle=lambda rect: SimpleNamespace(WorkingArea=work_area))))

    saved = dict(x=5000, y=-3000, width=form.Width, height=form.Height) if restore else None
    desktop._fit_window_to_work_area(SimpleNamespace(native=form), saved)

    assert area[0] <= form.Location.X
    assert area[1] <= form.Location.Y
    assert form.Location.X + form.Size.Width <= area[0] + area[2]
    assert form.Location.Y + form.Size.Height <= area[1] + area[3]
    assert form.MinimumSize.Width <= form.Size.Width
    assert form.MinimumSize.Height <= form.Size.Height
    assert form.Size.Width == min(int(1440 * scale), area[2])
    assert form.Size.Height == min(int(1000 * scale), area[3])
    assert form.StartPosition == 'manual'


@pytest.fixture
def timers(monkeypatch):
    factory = Mock(side_effect=lambda *args, **kwargs: Mock(args=args, kwargs=kwargs))
    monkeypatch.setattr(desktop, 'Timer', factory)
    return factory


@pytest.mark.parametrize('event', ['shown', 'stop'])
@pytest.mark.parametrize('before_start', [True, False])
def test_success_or_shutdown_disarms_deadline(timers, event, before_start):
    shutdown = Mock()
    guard = desktop.NativeStartupGuard(shutdown)
    if before_start:
        getattr(guard, event)()
    asyncio.run(guard.start())
    if not before_start:
        timer = guard._timer
        getattr(guard, event)()
        timer.cancel.assert_called_once()
    # 이미 실행 대기 중인 타이머 콜백도 취소된 상태를 확인해야 한다.
    loop = Mock()
    guard._timeout(loop)
    loop.call_soon_threadsafe.assert_not_called()
    shutdown.assert_not_called()
    assert timers.call_count == (0 if before_start else 1)


def test_timeout_requests_shutdown_once_and_keeps_fallback(timers, caplog):
    shutdown = Mock()
    guard = desktop.NativeStartupGuard(shutdown)
    asyncio.run(guard.start())
    asyncio.run(guard.start())
    assert timers.call_count == 1
    assert timers.call_args.args[0] == 30
    loop = Mock()
    guard._timeout(loop)
    loop.call_soon_threadsafe.assert_called_once_with(shutdown)
    assert timers.call_args.args == (5, desktop._force_native_exit)
    fallback = guard._exit_timer
    fallback.start.assert_called_once()
    guard.shown()
    guard.stop()
    guard._timeout(loop)
    fallback.cancel.assert_not_called()
    assert timers.call_count == 2
    assert '창이 표시되지 않아' in caplog.text


def test_closed_loop_still_has_force_exit(timers):
    guard = desktop.NativeStartupGuard(Mock())
    loop = Mock()
    loop.call_soon_threadsafe.side_effect = RuntimeError('closed')
    guard._timeout(loop)
    guard._exit_timer.start.assert_called_once()


def test_force_exit_cleans_children_even_if_one_terminate_fails(monkeypatch):
    children = [Mock(), Mock()]
    children[0].terminate.side_effect = OSError('already gone')
    monkeypatch.setattr(desktop.multiprocessing, 'active_children', lambda: children)
    exit_process = Mock()
    monkeypatch.setattr(desktop, '_exit_after_flush', exit_process)
    desktop._force_native_exit()
    for child in children:
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
    exit_process.assert_called_once_with(1)


@pytest.mark.parametrize('failure', ['create', 'start'])
def test_spawned_window_failure_exits_despite_live_threads(tmp_path, failure):
    # 실제 NiceGUI 창 진입점을 실행하되 OS 웹뷰만 대체한다.
    script = tmp_path / 'window_failure.py'
    script.write_text(textwrap.dedent(f'''
        import logging
        import multiprocessing as mp
        from pathlib import Path
        from unittest.mock import Mock, MagicMock
        from nicegui.native import native_mode
        from maeumnarae.core import desktop

        logging.basicConfig()
        desktop.log_folders = lambda database_path=None: (Path({str(tmp_path / 'logs')!r}),)
        native_mode.helpers.is_port_open = lambda *args: True
        native_mode.webview = Mock()
        native_mode.webview.create_window.return_value = MagicMock()
        native_mode.webview.{'create_window' if failure == 'create' else 'start'}.side_effect = RuntimeError('injected {failure} failure')
        desktop.register_native_startup_guard()
        original = desktop._original_open_window
        desktop.register_native_startup_guard()
        assert desktop._original_open_window is original

        if __name__ == '__main__':
            ctx = mp.get_context('spawn')
            method_queue, response_queue = ctx.Queue(), ctx.Queue()
            process = ctx.Process(target=native_mode._open_window, args=(
                'http', '127.0.0.1', 9999, 'test', 800, 600, False, False,
                method_queue, response_queue, None))
            process.start()
            process.join(10)
            if process.is_alive():
                process.kill()
                process.join()
                raise AssertionError('window process stayed alive')
            assert process.exitcode == 1, process.exitcode
    '''), encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                            timeout=20, env=env)
    assert result.returncode == 0, result.stderr
    assert f'injected {failure} failure' in result.stderr
    assert 'Traceback' in result.stderr


@pytest.mark.parametrize('native,frozen,expected_reload', [
    (True, False, False), (True, True, False),
    (False, False, True), (False, True, False),
])
def test_run_modes(monkeypatch, native, frozen, expected_reload):
    from maeumnarae import application

    monkeypatch.setattr(sys, 'argv', ['main.py', '--native' if native else '--browser', '--port', '8765'])
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(application, 'configure_logging', Mock())
    configure = Mock()
    monkeypatch.setattr(application, 'configure_native', configure)
    monkeypatch.setattr(application, 'register_page', Mock())
    run = Mock()
    monkeypatch.setattr(application.ui, 'run', run)
    application.main()
    assert configure.call_count == int(native)
    assert run.call_args.kwargs['reload'] is expected_reload


def test_native_hooks_use_shown_event(monkeypatch):
    from nicegui import app

    native = Mock(window_args={}, settings={}, start_args={})
    monkeypatch.setattr(app, 'native', native)
    startup, shutdown = Mock(), Mock()
    monkeypatch.setattr(app, 'on_startup', startup)
    monkeypatch.setattr(app, 'on_shutdown', shutdown)
    desktop.configure_native()
    guard = startup.call_args.args[0].__self__
    shutdown.assert_called_once_with(guard.stop)
    native.on.assert_called_once_with('shown', guard.shown)


@pytest.mark.parametrize('failure', ['start', 'timeout'])
def test_native_server_releases_port_on_window_failure(tmp_path, failure):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    script = tmp_path / 'server_failure.py'
    pid_file = tmp_path / 'window.pid'
    script.write_text(textwrap.dedent(f'''
        import asyncio
        import os
        from pathlib import Path
        from threading import Event
        from unittest.mock import Mock, MagicMock
        from nicegui import app, ui
        from nicegui.native import native_mode
        from maeumnarae.core import desktop

        desktop.log_folders = lambda database_path=None: (Path({str(tmp_path / 'logs')!r}),)

        def create_window(**kwargs):
            Path({str(pid_file)!r}).write_text(str(os.getpid()))
            return MagicMock()

        def start_window(**kwargs):
            if {failure!r} == 'start':
                raise RuntimeError('injected backend failure')
            Event().wait()

        native_mode.webview = Mock(create_window=create_window, start=start_window)
        desktop.register_native_startup_guard()
        desktop.NATIVE_START_TIMEOUT = 1
        desktop.NATIVE_SHUTDOWN_GRACE = 0.3

        if __name__ == '__main__':
            desktop.configure_native()
            if {failure!r} == 'timeout':
                async def stuck_shutdown():
                    await asyncio.Event().wait()
                app.on_shutdown(stuck_shutdown)
            ui.run(native=True, host='127.0.0.1', port={port}, reload=False, show=False)
    '''), encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    env.pop('PYTEST_CURRENT_TEST', None)
    try:
        result = subprocess.run([sys.executable, str(script)], capture_output=True,
                                text=True, timeout=20, env=env)
        assert result.returncode == (1 if failure == 'timeout' else 0), result.stderr
        assert pid_file.exists(), result.stderr
        if failure == 'timeout':
            assert '강제 종료합니다' in result.stderr
        else:
            assert 'injected backend failure' in (tmp_path / 'logs' / 'maeumnarae.log').read_text()
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0
        pid = int(pid_file.read_text())
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail('window subprocess remained after server exit')
    finally:
        if pid_file.exists():
            try:
                import signal
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
