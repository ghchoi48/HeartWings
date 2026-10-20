"""화면 설정 복원, 잘못된 값 방어 및 네이티브 아이콘 전달 검사."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from desktop import update_native_icon
from views.display_settings import DisplaySettings


def test_defaults_and_saved_preferences():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'display-settings.json'
        settings = DisplaySettings(path)
        assert settings.values == {'mode': 'auto', 'size': 16, 'font': 'system'}
        with patch('views.display_settings.ui.run_javascript'):
            settings.change('mode', 'dark')
            settings.change('size', 19)
            settings.change('font', 'PretendardVariable.ttf')
        assert DisplaySettings(path).values == {'mode': 'dark', 'size': 19, 'font': 'PretendardVariable.ttf'}


def test_invalid_settings_fall_back_to_defaults():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'display-settings.json'
        for contents in ('broken json', 'null', json.dumps({'mode': 'bad', 'size': 900, 'font': 'bad'}),
                         json.dumps({'font': 'serif'}), json.dumps({'font': 'removed-font.ttf'})):
            path.write_text(contents)
            assert DisplaySettings(path).values == {'mode': 'auto', 'size': 16, 'font': 'system'}


def test_native_icon_uses_window_process_only():
    with patch('nicegui.native.native.method_queue', None):
        update_native_icon(True)
    queue = Mock()
    with patch('nicegui.native.native.method_queue', queue):
        update_native_icon(True)
        update_native_icon(False)
    assert [call.args[0] for call in queue.put.call_args_list] == [
        ('set_app_icon', (True,), {}), ('set_app_icon', (False,), {}),
    ]
