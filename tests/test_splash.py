"""실제 Windows GUI 없이 부모/자식 및 시작 종료 경계를 검증한다."""

import asyncio
import sys
from unittest.mock import Mock

import pytest

from maeumnarae.core import desktop, splash


@pytest.fixture
def backend(monkeypatch):
    module = Mock()
    monkeypatch.setitem(sys.modules, 'pyi_splash', module)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('_PYI_SPLASH_IPC', '12345')
    monkeypatch.setattr(splash, '_closed', False)
    return module


def test_close_is_idempotent(backend):
    splash.close_splash()
    splash.close_splash()
    backend.close.assert_called_once()


@pytest.mark.parametrize('frozen,port', [(False, '12345'), (True, '0'), (True, None)])
def test_source_or_child_does_not_touch_splash(backend, monkeypatch, frozen, port):
    monkeypatch.setattr(sys, 'frozen', frozen)
    if port is None:
        monkeypatch.delenv('_PYI_SPLASH_IPC')
    else:
        monkeypatch.setenv('_PYI_SPLASH_IPC', port)
    splash.close_splash()
    backend.close.assert_not_called()


@pytest.mark.parametrize('args,closed', [([], False), (['--native'], False),
                                      (['--browser'], True), (['--help'], True)])
def test_bootstrap_installs_cleanup(backend, monkeypatch, args, closed):
    monkeypatch.setattr(sys, 'argv', ['maeumnarae.exe', *args])
    register = Mock()
    monkeypatch.setattr(splash.atexit, 'register', register)
    splash.configure_splash()
    register.assert_called_once_with(splash.close_splash)
    assert backend.close.called is closed
    register.call_args.args[0]()
    backend.close.assert_called_once()


@pytest.mark.parametrize('event', ['shown', 'stop', 'timeout'])
def test_guard_keeps_splash_until_window_or_failure(backend, monkeypatch, event):
    monkeypatch.setattr(desktop, 'Timer', Mock())
    guard = desktop.NativeStartupGuard(Mock())
    asyncio.run(guard.start())
    backend.close.assert_not_called()
    if event == 'timeout':
        guard._timeout(Mock())
    else:
        getattr(guard, event)()
    backend.close.assert_called_once()
    guard.stop()
    backend.close.assert_called_once()


def test_ipc_failure_does_not_break_startup(backend):
    backend.close.side_effect = OSError('disconnected')
    splash.close_splash()
    assert not splash._closed
