"""화면 설정 복원, 잘못된 값 방어 및 네이티브 아이콘 전달 검사."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from maeumnarae.core.desktop import update_native_icon
from maeumnarae.views.display_settings import (DisplaySettings, DEFAULT_PRIMARY, PRIMARY_PRESETS,
                                    luminance, primary_text_color, readable_accent)


def test_defaults_and_saved_preferences():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'display-settings.json'
        settings = DisplaySettings(path)
        assert settings.values == {'mode': 'auto', 'size': 16, 'font': 'SpoqaHanSansNeo', 'primary': DEFAULT_PRIMARY}
        with patch('maeumnarae.views.display_settings.ui.run_javascript'):
            settings.change('mode', 'dark')
            settings.change('size', 19)
            settings.change('font', 'PretendardVariable.ttf')
        assert DisplaySettings(path).values == {'mode': 'dark', 'size': 19, 'font': 'PretendardVariable.ttf', 'primary': DEFAULT_PRIMARY}


def test_invalid_settings_fall_back_to_defaults():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'display-settings.json'
        for contents in ('broken json', 'null', json.dumps({'mode': 'bad', 'size': 900, 'font': 'bad'}),
                         json.dumps({'font': 'serif'}), json.dumps({'font': 'removed-font.ttf'})):
            path.write_text(contents)
            assert DisplaySettings(path).values == {'mode': 'auto', 'size': 16, 'font': 'SpoqaHanSansNeo', 'primary': DEFAULT_PRIMARY}


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


def test_primary_persistence_and_invalid_colors(tmp_path):
    path = tmp_path / 'display-settings.json'
    path.write_text(json.dumps({'widget_setting': 'preserved'}))
    settings = DisplaySettings(path)
    with patch('maeumnarae.views.display_settings.ui.colors') as colors, \
            patch('maeumnarae.views.display_settings.ui.run_javascript') as javascript:
        settings.change('primary', '#Fa0')
        colors.assert_called_once_with(primary='#ffaa00')
        assert '--app-primary-text' in javascript.call_args.args[0]
        assert DisplaySettings(path).values['primary'] == '#ffaa00'
        assert json.loads(path.read_text())['widget_setting'] == 'preserved'
        for value in (None, 123, 'red', '#12345', '#12345678', '#ffffff; color:red'):
            settings.change('primary', value)
            assert settings.values['primary'] == '#ffaa00'
        colors.assert_called_once()
    path.write_text(json.dumps({'primary': 'invalid'}))
    assert DisplaySettings(path).values['primary'] == DEFAULT_PRIMARY


def test_primary_contrast_on_light_and_dark_surfaces():
    assert primary_text_color('#ffffff') == '#000000'
    assert primary_text_color('#000000') == '#ffffff'
    for color in [*PRIMARY_PRESETS.values(), '#ffffff', '#000000', '#777777', '#00ff00']:
        low, high = sorted((luminance(color), luminance(primary_text_color(color))))
        assert (high + 0.05) / (low + 0.05) >= 4.5
        for background in ('#ffffff', '#1e293b'):
            accent = readable_accent(color, background)
            low, high = sorted((luminance(accent), luminance(background)))
            assert (high + 0.05) / (low + 0.05) >= 4.5


def test_color_picker_and_preset_controls():
    from nicegui import Client, ui
    from nicegui.page import page
    from types import SimpleNamespace
    with Client(page('/primary-settings-test')), \
            patch('maeumnarae.views.display_settings.ui.run_javascript'), \
            patch('maeumnarae.views.display_settings.ui.colors'):
        settings = DisplaySettings()
        settings.build_controls()
        elements = list(ui.context.client.elements.values())
        picker = next(element for element in elements if isinstance(element, ui.color_picker))
        assert picker.q_color.props['model-value'] == DEFAULT_PRIMARY
        assert picker.q_color.props['format-model'] == 'hex'
        assert len([element for element in elements
                    if isinstance(element, ui.button) and element.text in PRIMARY_PRESETS]) == 5
        picker._pick_handlers[0](SimpleNamespace(color='#ffffff'))
        assert settings.values['primary'] == '#ffffff'
        assert picker.q_color.props['model-value'] == '#ffffff'
        assert any(isinstance(element, ui.label) and element.text == '#FFFFFF' for element in elements)
