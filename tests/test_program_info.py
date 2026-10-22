"""프로그램 라이선스 전문과 추가 라이선스 자료의 로딩을 검증한다."""

import json
from unittest.mock import patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

import program_info
from views.about_view import build_about


def test_about_shows_author_github_and_full_mit_license():
    with Client(page('/about-test')) as client:
        build_about()
        labels = [element.text for element in client.elements.values() if isinstance(element, ui.label)]
        assert f'제작자: {program_info.AUTHOR}' in labels
        assert program_info.program_license() in labels
        assert any(isinstance(element, ui.link) and element.props['href'] == program_info.GITHUB_URL
                   for element in client.elements.values())
        assert 'MIT License' in program_info.program_license()


def test_manifest_loads_library_and_font_license_text(tmp_path):
    root = tmp_path / 'licenses'
    root.mkdir()
    text = 'Copyright Example\nPermission notice <original>\n'
    (root / 'example.txt').write_text(text, encoding='utf-8')
    entry = {'name': 'Example', 'license': 'MIT', 'text_file': 'example.txt'}
    (root / 'manifest.json').write_text(json.dumps({'libraries': [entry], 'fonts': [entry]}), encoding='utf-8')
    with patch.object(program_info, 'RESOURCE_ROOT', tmp_path):
        notices = program_info.third_party_notices()
    assert notices['libraries'][0]['text'] == text
    assert notices['fonts'][0]['text'] == text


def test_manifest_rejects_license_path_outside_folder(tmp_path):
    root = tmp_path / 'licenses'
    root.mkdir()
    (root / 'manifest.json').write_text(json.dumps({
        'libraries': [{'name': 'Example', 'text_file': '../outside.txt'}],
    }), encoding='utf-8')
    with patch.object(program_info, 'RESOURCE_ROOT', tmp_path), pytest.raises(ValueError):
        program_info.third_party_notices()
