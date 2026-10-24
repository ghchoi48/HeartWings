"""자동 잠금의 만료 경계, 입력 갱신, 저장 및 화면 연결 검사."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.settings_store import SettingsStore
from maeumnarae.views.auto_lock import AutoLock, AUTO_LOCK_MINUTES


def test_defaults_restore_and_preserve_other_settings(tmp_path):
    path = tmp_path / 'settings.json'
    store = SettingsStore(path)
    store.update(lambda data: data.update(mode='dark', widgets=['memo']))
    lock = AutoLock(store, AsyncMock())
    assert lock.minutes == 20
    for minutes in AUTO_LOCK_MINUTES:
        asyncio.run(lock.change_minutes(minutes))
        assert AutoLock(store, AsyncMock()).minutes == minutes
        assert lock.remaining == minutes * 60
    assert store.read()['mode'] == 'dark'
    assert store.read()['widgets'] == ['memo']
    for value in (None, True, 0, 15, '20', 20.0):
        path.write_text(json.dumps({'auto_lock_minutes': value}))
        assert AutoLock(store, AsyncMock()).minutes == 20
    path.write_text('invalid json')
    assert AutoLock(store, AsyncMock()).minutes == 20


def test_activity_resets_countdown_and_expiry_locks_once():
    async def scenario():
        clock = Mock(return_value=1000)
        callback = AsyncMock()
        lock = AutoLock(SettingsStore(None), callback, clock)
        lock.label = Mock()
        clock.return_value = 1061
        await lock.tick()
        lock.label.set_text.assert_called_with('자동 잠금 18:59')
        callback.assert_not_awaited()
        await lock.activity()
        assert lock.remaining == 1200
        clock.return_value = 2260.1
        await lock.tick()
        assert lock.remaining == 1
        callback.assert_not_awaited()
        clock.return_value = 2261
        await asyncio.gather(lock.tick(), lock.activity(), lock.lock())
        callback.assert_awaited_once()
        assert lock.locked
        assert lock.last_activity == 1061
    asyncio.run(scenario())


def test_resume_after_deadline_does_not_reset_or_change_timeout():
    async def scenario():
        clock = Mock(return_value=0)
        callback = AsyncMock()
        lock = AutoLock(SettingsStore(None), callback, clock)
        clock.return_value = 7200
        await lock.change_minutes(60)
        callback.assert_awaited_once()
        assert lock.minutes == 20
    asyncio.run(scenario())


def test_save_failure_keeps_active_timeout(tmp_path):
    lock = AutoLock(SettingsStore(tmp_path / 'settings.json'), AsyncMock())
    with patch.object(lock.store, 'update', side_effect=OSError), patch('maeumnarae.views.auto_lock.ui.notify') as notify:
        asyncio.run(lock.change_minutes(5))
    assert lock.minutes == 5
    notify.assert_called_once()


def test_header_timer_and_settings_options():
    with Client(page('/auto-lock-test')), patch('maeumnarae.views.auto_lock.ui.run_javascript') as javascript, \
            patch('maeumnarae.views.auto_lock.ui.timer') as timer:
        lock = AutoLock(SettingsStore(None), AsyncMock())
        lock.install()
        lock.build_controls()
        assert lock.label.text == '자동 잠금 20:00'
        select = next(e for e in ui.context.client.elements.values() if isinstance(e, ui.select))
        assert select.value == 20
        assert list(select.options) == [5, 10, 20, 30, 40, 50, 60]
        assert 'keydown' in javascript.call_args.args[0]
        assert 'capture: true' in javascript.call_args.args[0]
        timer.assert_called_once_with(1, lock.tick)
        asyncio.run(lock.lock())
        timer.return_value.deactivate.assert_called_once()
