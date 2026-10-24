"""번들 fonts 폴더의 글꼴 목록과 브라우저용 @font-face 정의."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from maeumnarae.core.paths import RESOURCE_ROOT

FONT_DIRECTORY = RESOURCE_ROOT / 'fonts'
FORMATS = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}
LABELS = {
    'PretendardVariable.ttf': 'Pretendard',
    'NotoSansKR-VariableFont_wght.ttf': 'Noto Sans KR',
    'SpoqaHanSansNeo': 'Spoqa Han Sans Neo',
}
SPOQA_WEIGHTS = {'Thin': 250, 'Light': 300, 'Regular': 400, 'Medium': 500, 'Bold': 700}
FONT_FILES = tuple(sorted(
    (path for path in FONT_DIRECTORY.rglob('*')
     if path.is_file() and not path.is_symlink() and path.suffix.lower() in FORMATS),
    key=lambda path: path.relative_to(FONT_DIRECTORY).as_posix(),
))
FONTS = {'system': '시스템 기본'}
FONT_FAMILIES = {'system': 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'}


def font_key(path: Path) -> str:
    relative = path.relative_to(FONT_DIRECTORY)
    if relative.parent.as_posix() == 'SpoqaHanSansNeo' and path.stem in {
        f'SpoqaHanSansNeo-{weight}' for weight in SPOQA_WEIGHTS
    }:
        return 'SpoqaHanSansNeo'
    return relative.as_posix()


def font_family(path: Path) -> str:
    return 'AppFont_' + hashlib.sha256(font_key(path).encode('utf-8')).hexdigest()[:16]


def font_weight(path: Path) -> str:
    if font_key(path) == 'SpoqaHanSansNeo':
        return str(SPOQA_WEIGHTS[path.stem.rsplit('-', 1)[1]])
    return '100 900' if 'variable' in path.name.lower() else '400'


def font_url(path: Path) -> str:
    return '/app-fonts/' + quote(path.relative_to(FONT_DIRECTORY).as_posix(), safe='/')


for font in FONT_FILES:
    key = font_key(font)
    FONTS[key] = LABELS.get(key, font.stem)
    FONT_FAMILIES[key] = f'"{font_family(font)}", system-ui, sans-serif'


def font_face_css() -> str:
    return '\n'.join(
        '@font-face {'
        f'font-family: "{font_family(font)}";'
        f'src: url({json.dumps(font_url(font))}) format("{FORMATS[font.suffix.lower()]}");'
        f'font-weight: {font_weight(font)};'
        'font-style: normal; font-display: swap;'
        '}'
        for font in FONT_FILES
    )


def register_fonts() -> None:
    from nicegui import app
    for font in FONT_FILES:
        app.add_static_file(url_path=font_url(font), local_file=font)
