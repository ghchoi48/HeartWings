"""공개 GitHub Releases의 최신 정식 버전 조회."""

import json
import re
import ssl
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi

from maeumnarae.core.program_info import GITHUB_URL, PROGRAM_VERSION


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str


def version_numbers(value: str) -> tuple[int, int, int] | None:
    """v 접두사가 있는 major.minor.patch 정식 태그도 허용한다."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z.-]+)?', value)
    return tuple(int(part) for part in match.groups()) if match else None


def fetch_update(current_version: str = PROGRAM_VERSION) -> Release | None:
    current = version_numbers(current_version)
    if current is None:
        return None
    repository = GITHUB_URL.removeprefix('https://github.com/')
    request = Request(f'https://api.github.com/repos/{repository}/releases/latest', headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': f'HeartWings/{current_version}',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urlopen(request, timeout=8,
                     context=ssl.create_default_context(cafile=certifi.where())) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
            return None
        tag = data.get('tag_name')
        latest = version_numbers(tag)
        if latest is None or latest <= current:
            return None
        notes = data.get('body')
        if not isinstance(notes, str) or not notes.strip():
            notes = '등록된 변경사항이 없습니다.'
        return Release(tag, notes, f'{GITHUB_URL}/releases/tag/{quote(tag, safe="")}')
    except (OSError, ValueError):
        # 오프라인, 시간 초과, API 제한, 릴리스 없음은 앱 시작을 방해하지 않는다.
        return None


def fetch_release_history(page: int = 1) -> tuple[list[Release], bool]:
    """공개 릴리스 내역 한 페이지와 다음 페이지 가능 여부를 반환한다."""
    if page < 1:
        raise ValueError('페이지는 1 이상이어야 합니다.')
    repository = GITHUB_URL.removeprefix('https://github.com/')
    request = Request(f'https://api.github.com/repos/{repository}/releases?per_page=20&page={page}', headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': f'HeartWings/{PROGRAM_VERSION}',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urlopen(request, timeout=8,
                 context=ssl.create_default_context(cafile=certifi.where())) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError('업데이트 내역이 너무 큽니다.')
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError('업데이트 내역 형식이 올바르지 않습니다.')
    releases = []
    for item in data:
        if not isinstance(item, dict) or item.get('draft') or item.get('prerelease'):
            continue
        tag = item.get('tag_name')
        if version_numbers(tag) is None:
            continue
        notes = item.get('body')
        if not isinstance(notes, str) or not notes.strip():
            notes = '등록된 변경사항이 없습니다.'
        releases.append(Release(tag, notes, f'{GITHUB_URL}/releases/tag/{quote(tag, safe="")}'))
    return releases, len(data) == 20
