"""업데이트 버전 비교, 네트워크 실패, 시작 시 중복 확인 및 알림 UI 검증."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError, URLError

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.services.updates import Release, fetch_update
from maeumnarae.views.update_notification import StartupUpdateCheck, show_update_dialog


def response_for(payload):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(payload).encode()
    return response


@pytest.mark.parametrize('tag,expected', [
    ('v1.2.1', True), ('1.10.0', True), ('1.2.0', False),
    ('v1.1.9', False), ('2.0.0', True), ('v2.0.0-rc.1', False),
    ('latest', False), (None, False), ('1.2.0+build.2', False),
])
def test_versions(tag, expected):
    with patch('maeumnarae.services.updates.urlopen', return_value=response_for({'tag_name': tag, 'body': '수정사항'})) as request:
        release = fetch_update('1.2.0')
    assert (release is not None) == expected
    assert request.call_args.kwargs['timeout'] == 8
    if release:
        assert release.notes == '수정사항'
        assert release.url.startswith('https://github.com/ghchoi48/HeartWings/releases/tag/')


@pytest.mark.parametrize('payload', [[], None, {}, {'tag_name': 'v2.0.0', 'draft': True},
                                     {'tag_name': 'v2.0.0', 'prerelease': True}])
def test_invalid_or_unpublished_release(payload):
    with patch('maeumnarae.services.updates.urlopen', return_value=response_for(payload)):
        assert fetch_update() is None


@pytest.mark.parametrize('error', [URLError('offline'), TimeoutError(),
                                   HTTPError('url', 404, 'missing', {}, None),
                                   HTTPError('url', 403, 'rate limit', {}, None)])
def test_network_failure_is_ignored(error):
    with patch('maeumnarae.services.updates.urlopen', side_effect=error):
        assert fetch_update() is None


def test_empty_notes_and_invalid_response():
    response = response_for({'tag_name': 'v2.0.0', 'body': None})
    with patch('maeumnarae.services.updates.urlopen', return_value=response):
        assert fetch_update().notes == '등록된 변경사항이 없습니다.'
        response.read.return_value = b'not json'
        assert fetch_update() is None
        response.read.return_value = b'x' * 1_000_001
        assert fetch_update() is None


def test_check_runs_once_even_with_concurrent_pages():
    release = Release('v2.0.0', '변경사항', 'https://github.com/ghchoi48/HeartWings/releases/tag/v2.0.0')
    async def scenario():
        check = StartupUpdateCheck()
        with patch('maeumnarae.views.update_notification.run.io_bound', new_callable=AsyncMock, return_value=release) as fetch, \
                patch('maeumnarae.views.update_notification.show_update_dialog') as show:
            await asyncio.gather(check.check(), check.check())
            await check.check()
            fetch.assert_awaited_once()
            show.assert_called_once_with(release)
    asyncio.run(scenario())


def test_no_update_shows_no_dialog():
    with patch('maeumnarae.views.update_notification.run.io_bound', new_callable=AsyncMock, return_value=None), \
            patch('maeumnarae.views.update_notification.show_update_dialog') as show:
        asyncio.run(StartupUpdateCheck().check())
        show.assert_not_called()


def test_dialog_contains_notes_and_footer_actions():
    release = Release('v2.0.0', '변경사항\n<script>example</script>', 'https://github.com/ghchoi48/HeartWings/releases/tag/v2.0.0')
    with Client(page('/updates-test')) as client:
        show_update_dialog(release)
        labels = [element.text for element in client.elements.values() if isinstance(element, ui.label)]
        assert '새 버전 알림' in labels
        assert release.notes in labels
        buttons = {element.text: element for element in client.elements.values() if isinstance(element, ui.button)}
        assert set(buttons) == {'취소', '다운로드 페이지 이동'}
        dialog = next(element for element in client.elements.values() if isinstance(element, ui.dialog))
        assert dialog.value
        cancel = next(iter(buttons['취소']._event_listeners.values())).handler
        cancel(None)
        assert not dialog.value
        download = next(iter(buttons['다운로드 페이지 이동']._event_listeners.values())).handler
        with patch('nicegui.elements.button.handle_event') as dispatch:
            download(None)
        with patch('maeumnarae.views.update_notification.run.io_bound', new_callable=AsyncMock) as open_page:
            asyncio.run(dispatch.call_args.args[0]())
            assert open_page.call_args.args[1] == release.url
