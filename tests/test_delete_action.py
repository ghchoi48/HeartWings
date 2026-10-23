"""실제 UI 확인창의 취소·확인 및 오류 후 재시도를 검증한다."""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import DatabaseError
from views.delete_action import delete_button


@pytest.mark.parametrize('confirmed', [False, True])
def test_confirmation_captures_target_and_refreshes_only_after_success(confirmed):
    async def scenario():
        client = Client(page('/delete-test'))
        with client:
            target = SimpleNamespace(id=7, name='삭제 대상')
            current = [target]
            refresh = AsyncMock()
            button = delete_button(Mock(), 'student', lambda: current[0], refresh)
            handler = next(item.handler for item in button._event_listeners.values() if item.type == 'click')

            async def confirm(dialog):
                assert any(isinstance(child, ui.label) and '삭제 대상' in child.text for child in dialog.descendants())
                # 다른 선택으로 바뀌어도 확인창에 표시했던 대상만 삭제한다.
                current[0] = SimpleNamespace(id=8, name='다른 학생')
                return confirmed

            with patch.object(ui.dialog, '__await__', lambda dialog: confirm(dialog).__await__()), \
                    patch('views.delete_action.run.io_bound', new_callable=AsyncMock) as io, \
                    patch('views.delete_action.ui.notify'):
                await inspect.getclosurevars(handler).nonlocals['callback']()
                if confirmed:
                    assert io.await_args.args[1:] == ('student', 7)
                    refresh.assert_awaited_once()
                else:
                    io.assert_not_awaited()
                    refresh.assert_not_awaited()
                assert button.enabled
        client.delete()
    asyncio.run(scenario())


def test_failure_keeps_view_and_allows_retry():
    async def scenario():
        client = Client(page('/delete-error-test'))
        with client:
            refresh = AsyncMock()
            button = delete_button(Mock(), 'event', lambda: SimpleNamespace(id=1, title='일정'), refresh)
            handler = next(item.handler for item in button._event_listeners.values() if item.type == 'click')

            async def confirm(dialog):
                return True

            with patch.object(ui.dialog, '__await__', lambda dialog: confirm(dialog).__await__()), \
                    patch('views.delete_action.run.io_bound', new_callable=AsyncMock, side_effect=[DatabaseError('잠금'), None]), \
                    patch('views.delete_action.ui.notify'):
                await inspect.getclosurevars(handler).nonlocals['callback']()
                refresh.assert_not_awaited()
                assert button.enabled
                await inspect.getclosurevars(handler).nonlocals['callback']()
                refresh.assert_awaited_once()
        client.delete()
    asyncio.run(scenario())
