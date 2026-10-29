"""Verify release hashes and optional frozen execution evidence without extracting files."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile


def local_file(folder: Path, name: str) -> Path:
    if Path(name).name != name or '\\' in name:
        raise ValueError('릴리스 파일명은 같은 폴더의 파일이어야 합니다.')
    return folder / name


def check(release_json: Path, frozen_report: Path | None = None) -> dict:
    info = json.loads(release_json.read_text(encoding='utf-8'))
    folder = release_json.parent
    source = local_file(folder, info['source_archive'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != info['source_archive_sha256']:
        raise ValueError('릴리스 소스 ZIP 해시가 다릅니다.')
    for name, digest in info['artifacts_sha256'].items():
        if hashlib.sha256(local_file(folder, name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'실행 파일 해시가 다릅니다: {name}')
    with ZipFile(source) as archive:
        for name, digest in info['source_files_sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError(f'소스 파일 해시가 다릅니다: {name}')
        internal = json.loads(archive.read('release/build-environment.json'))
        if any(info[key] != value for key, value in internal.items()):
            raise ValueError('소스 ZIP과 릴리스 환경 기록이 다릅니다.')
        if frozen_report:
            runtime = json.loads(frozen_report.read_text(encoding='utf-8'))
            if info['status'] != 'paired-build' or not info['artifacts_sha256']:
                raise ValueError('실행 파일과 연결되지 않은 소스 자료입니다.')
            if runtime.get('status') != 'passed' or not runtime.get('frozen'):
                raise ValueError('성공한 frozen 실행 결과가 아닙니다.')
            if runtime['pyxlsb_version'] != info['environment']['packages']['pyxlsb']:
                raise ValueError('기록된 환경과 실제 실행된 pyxlsb 버전이 다릅니다.')
            baseline = json.loads(archive.read('tests/fixtures/legacy_import/baseline.json'))
            if runtime['fingerprint'] != baseline['fingerprint']:
                raise ValueError('기존 이관 지문과 실행 결과가 다릅니다.')
            manifest = json.loads(archive.read('resources/licenses/manifest.json'))
            for entry in manifest['libraries']:
                if entry['name'] in ('pyxlsb', 'certifi'):
                    digest = hashlib.sha256(archive.read('resources/licenses/' + entry['source_file'])).hexdigest()
                    if runtime['source_sha256'][entry['name']] != digest:
                        raise ValueError('실행 파일과 릴리스 원본 소스가 다릅니다.')
                    if entry.get('modified_source_file'):
                        content = archive.read('resources/licenses/' + entry['modified_source_file'])
                        if runtime['source_sha256']['used_sources'] != hashlib.sha256(content).hexdigest():
                            raise ValueError('실행 파일과 릴리스 사용 소스가 다릅니다.')
                        with ZipFile(BytesIO(content)) as used:
                            if json.loads(used.read('CONTENTS.json'))['installed_version'] != runtime['pyxlsb_version']:
                                raise ValueError('동봉 소스의 버전이 다릅니다.')
    return {'integrity': 'passed', 'runtime': 'passed' if frozen_report else 'not_checked',
            'release_status': info['status'], 'target': info['target'],
            'source_files': len(info['source_files_sha256']), 'gui': 'not_checked'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release_json', type=Path)
    parser.add_argument('--frozen-report', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.release_json, args.frozen_report), ensure_ascii=False, indent=2))
