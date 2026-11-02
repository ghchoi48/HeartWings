"""프로그램 소개 정보와 배포에 포함되는 라이선스 자료."""

import json
from maeumnarae.core.paths import PROJECT_ROOT


PROGRAM_NAME = '마음나래'
PROGRAM_VERSION = '1.1.1'
AUTHOR = '전문상담교사 최규호 with GPT-6 Astra'
GITHUB_URL = 'https://github.com/ghchoi48/HeartWings'
RESOURCE_ROOT = PROJECT_ROOT


def third_party_source(relative_path: str) -> bytes:
    """동봉 소스를 내려받을 때 라이선스 폴더 밖 접근을 막는다."""
    root = (RESOURCE_ROOT / 'resources' / 'licenses').resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('소스 파일은 licenses 폴더 안에 있어야 합니다.')
    return path.read_bytes()


def program_license() -> str:
    return (RESOURCE_ROOT / 'LICENSE').read_text(encoding='utf-8')


def third_party_notices() -> dict[str, list[dict[str, str]]]:
    """manifest의 text_file은 licenses 폴더 기준 상대 경로다."""
    root = RESOURCE_ROOT / 'resources' / 'licenses'
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    notices = {}
    for category in ('libraries', 'fonts'):
        notices[category] = []
        for entry in manifest.get(category, []):
            notice = dict(entry)
            notice['text'] = ''
            if entry.get('text_file'):
                path = (root / entry['text_file']).resolve()
                if not path.is_relative_to(root.resolve()):
                    raise ValueError('라이선스 파일은 licenses 폴더 안에 있어야 합니다.')
                notice['text'] = path.read_text(encoding='utf-8')
            notices[category].append(notice)
    return notices
