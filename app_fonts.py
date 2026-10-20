"""번들 fonts 폴더의 글꼴 목록과 브라우저용 @font-face 정의."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

FONT_DIRECTORY = Path(__file__).resolve().parent / 'fonts'
FORMATS = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}
LABELS = {
    'PretendardVariable.ttf': 'Pretendard',
    'NotoSansKR-VariableFont_wght.ttf': 'Noto Sans KR',
}
FONT_FILES = tuple(sorted(
    (path for path in FONT_DIRECTORY.glob('*')
     if path.is_file() and not path.is_symlink() and path.suffix.lower() in FORMATS),
    key=lambda path: path.name,
))
FONTS = {'system': '시스템 기본'}
FONT_FAMILIES = {'system': 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'}


def font_family(path: Path) -> str:
    return 'AppFont_' + hashlib.sha256(path.name.encode('utf-8')).hexdigest()[:16]


def font_url(path: Path) -> str:
    return '/app-fonts/' + quote(path.name, safe='')


for font in FONT_FILES:
    FONTS[font.name] = LABELS.get(font.name, font.stem)
    FONT_FAMILIES[font.name] = f'"{font_family(font)}", system-ui, sans-serif'


def font_face_css() -> str:
    return '\n'.join(
        '@font-face {'
        f'font-family: "{font_family(font)}";'
        f'src: url({json.dumps(font_url(font))}) format("{FORMATS[font.suffix.lower()]}");'
        f'font-weight: {"100 900" if "variable" in font.name.lower() else "400"};'
        'font-style: normal; font-display: swap;'
        '}'
        for font in FONT_FILES
    )


def register_fonts() -> None:
    from nicegui import app
    for font in FONT_FILES:
        app.add_static_file(url_path=font_url(font), local_file=font)
