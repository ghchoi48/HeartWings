"""동봉 원본 검증 및 현재 pyxlsb/앱 파생 소스 묶음 생성.

python packaging/prepare_pyxlsb_sources.py [--check]
원본과 다른 설치 소스도 그대로 수록한다. 사용자 수정본을 차단하지 않는다.
"""
import argparse
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


APP_FILES = (
    'maeumnarae/services/memory_xlsb.py',
    'maeumnarae/services/xlsb_reader.py',
    'LICENSE',
    'resources/licenses/pyxlsb/COPYING',
    'resources/licenses/pyxlsb/COPYING.LESSER',
    'resources/licenses/pyxlsb/PROVENANCE.md',
    'resources/licenses/libraries/pyxlsb.txt',
)


def source_bundle(root: Path, package_dir: Path, version: str) -> tuple[Path, bytes]:
    licenses = root / 'resources/licenses'
    manifest = json.loads((licenses / 'manifest.json').read_text(encoding='utf-8'))
    entry = next(item for item in manifest['libraries'] if item['name'] == 'pyxlsb')
    archive = licenses / entry['source_file']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != entry['source_sha256']:
        raise RuntimeError('동봉한 pyxlsb 기준 원본의 SHA-256이 일치하지 않습니다.')
    with tarfile.open(archive, 'r:gz') as source:
        prefix = f"pyxlsb-{entry['version']}/"
        for name in ('COPYING', 'COPYING.LESSER'):
            if source.extractfile(prefix + name).read() != (licenses / 'pyxlsb' / name).read_bytes():
                raise RuntimeError(f'pyxlsb {name} 원문이 공식 소스와 다릅니다.')
        originals = {
            member.name[len(prefix):]: source.extractfile(member).read()
            for member in source.getmembers()
            if member.isfile() and member.name.startswith(prefix + 'pyxlsb/')
        }
    installed = {
        'pyxlsb/' + path.relative_to(package_dir).as_posix(): path.read_bytes()
        for path in sorted(package_dir.rglob('*'))
        if path.is_file() and '__pycache__' not in path.parts
        and path.suffix not in ('.pyc', '.pyo')
    }
    if 'pyxlsb/__init__.py' not in installed:
        raise RuntimeError('설치된 pyxlsb의 Python 소스를 찾을 수 없습니다.')
    changed = sorted(name for name in originals.keys() | installed.keys()
                     if originals.get(name) != installed.get(name))
    observed = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    files = {name: (root / name).read_bytes() for name in APP_FILES}
    files.update(installed)
    # Include source build metadata alongside the installed library snapshot.
    with tarfile.open(archive, 'r:gz') as source:
        for name in ('setup.py', 'setup.cfg', 'MANIFEST.in', 'README.rst'):
            files['upstream-build-reference/' + name] = source.extractfile(prefix + name).read()
    changes = [f'# pyxlsb 변경 관찰 기록 ({observed})', '',
               f'공식 비교 기준: {entry["version"]}; 설치 모듈 버전: {version}',
               '날짜는 소스 묶음 생성/비교일이며 수정자의 원래 변경일을 추정하지 않습니다.', '',
               '원본과 달라진 파일: ' + (', '.join(changed) if changed else '없음'), '',
               '앱의 파생 구현 변경은 resources/licenses/pyxlsb/PROVENANCE.md를 참조하세요.',
               '수정본 배포자는 자신의 변경 설명·날짜·저작권 고지를 해당 소스에도 유지해야 합니다.', '']
    for name in changed:
        changes.extend(difflib.unified_diff(
            originals.get(name, b'').decode('utf-8', errors='replace').splitlines(),
            installed.get(name, b'').decode('utf-8', errors='replace').splitlines(),
            fromfile='upstream/' + name, tofile='included/' + name, lineterm=''))
    files['CHANGES.md'] = ('\n'.join(changes) + '\n').encode()
    files['README.md'] = ('''# XLSB 라이브러리 및 파생 구현 소스

pyxlsb/에는 빌드 환경에서 사용한 라이브러리 파일을, maeumnarae/services/에는
현재 앱의 파생 구현과 읽기 인터페이스를 수록합니다. 원본과의 차이는 CHANGES.md에 있습니다.
pyxlsb와 memory_xlsb.py는 LGPL-3.0-or-later, xlsb_reader.py는 MIT입니다.
LICENSE는 MIT 부분에만 적용됩니다. GPL/LGPL 전문과 저작권 고지는 resources/licenses/에 있습니다.
라이브러리 수정 및 수정 사항 디버깅을 위한 역공학을 제한하지 않습니다.

upstream-build-reference/는 공식 원본의 빌드 메타데이터 참고용입니다.
수정본의 빌드 설정을 대신하지 않으며 이 묶음은 앱 전체 재빌드 키트가 아닙니다.
앱 소스·의존성·재빌드 절차 제공은 별도 릴리스 자료로 준비해야 합니다.
CONTENTS.json은 수록 파일의 SHA-256과 설치 모듈 버전을 기록합니다.
''').encode()
    files['CONTENTS.json'] = (json.dumps({
        'upstream_version': entry['version'], 'installed_version': version,
        'upstream_sha256': entry['source_sha256'], 'observed_date': observed,
        'changed_upstream_files': changed,
        'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }, ensure_ascii=False, indent=2) + '\n').encode()
    output = BytesIO()
    with ZipFile(output, 'w') as bundle:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    return licenses / entry['modified_source_file'], output.getvalue()


def prepare(root: Path, package_dir: Path, version: str, *, check=False) -> Path:
    path, content = source_bundle(root, package_dir, version)
    if check:
        if not path.is_file() or path.read_bytes() != content:
            raise RuntimeError('XLSB 소스 묶음이 현재 코드와 다릅니다. 생성 명령을 다시 실행하세요.')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    import pyxlsb

    result = prepare(Path(__file__).resolve().parents[1], Path(pyxlsb.__file__).parent,
                     pyxlsb.__version__, check=args.check)
    print(f'XLSB 소스 {"확인" if args.check else "생성"}: {result}')
