"""분리된 정적 글꼴 파일의 패밀리 묶음과 굵기별 웹 등록 검증."""

from unittest.mock import patch
from nicegui import app

from maeumnarae.core.app_fonts import (
    FONT_DIRECTORY, FONT_FILES, FONTS, FONT_FAMILIES, font_face_css,
    font_family, font_key, font_url, font_weight, register_fonts,
)
from maeumnarae.views.display_settings import DisplaySettings


def test_spoqa_variants_share_one_option_and_family():
    variants = [font for font in FONT_FILES if font_key(font) == 'SpoqaHanSansNeo']
    assert len(variants) == 5
    assert [label for label in FONTS.values() if label.startswith('Spoqa')] == ['Spoqa Han Sans Neo']
    assert len({font_family(font) for font in variants}) == 1
    assert {font.stem.rsplit('-', 1)[1]: font_weight(font) for font in variants} == {
        'Thin': '250', 'Light': '300', 'Regular': '400', 'Medium': '500', 'Bold': '700',
    }
    css = font_face_css()
    for font in variants:
        assert font_url(font) in css
        assert f'font-weight: {font_weight(font)};' in css
    with patch.object(app, 'add_static_file') as register:
        register_fonts()
    for font in variants:
        register.assert_any_call(url_path=font_url(font), local_file=font)


def test_grouped_font_preference_persists(tmp_path):
    path = tmp_path / 'display-settings.json'
    settings = DisplaySettings(path)
    with patch('maeumnarae.views.display_settings.ui.run_javascript') as javascript:
        settings.change('font', 'SpoqaHanSansNeo')
    assert DisplaySettings(path).values['font'] == 'SpoqaHanSansNeo'
    assert 'AppFont_' in javascript.call_args.args[0]
    assert FONT_FAMILIES['SpoqaHanSansNeo'].startswith('"AppFont_')
    assert font_key(FONT_DIRECTORY / 'PretendardVariable.ttf') == 'PretendardVariable.ttf'
    assert font_weight(FONT_DIRECTORY / 'PretendardVariable.ttf') == '100 900'
