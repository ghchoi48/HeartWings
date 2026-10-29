"""배포하는 certifi와 동봉 MPL 소스의 일치를 PyInstaller 빌드 전에 확인한다."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import tarfile


def verify_certifi(root: Path, package_dir: Path, version: str) -> None:
    licenses = root / 'resources' / 'licenses'
    manifest = json.loads((licenses / 'manifest.json').read_text(encoding='utf-8'))
    entry = next(item for item in manifest['libraries'] if item['name'] == 'certifi')
    if version != entry['version']:
        raise RuntimeError('certifi 설치 버전과 고지 버전이 다릅니다. requirements/base.txt로 재설치하세요.')
    archive = licenses / entry['source_file']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != entry['source_sha256']:
        raise RuntimeError('동봉 certifi 소스의 SHA-256이 일치하지 않습니다.')
    requirement = f'certifi=={version}'
    if requirement not in (root / 'requirements/base.txt').read_text().splitlines():
        raise RuntimeError('certifi requirements 버전과 고지가 일치하지 않습니다.')
    prefix = f'certifi-{version}/'
    with tarfile.open(archive, 'r:gz') as source:
        if source.extractfile(prefix + 'LICENSE').read() != (licenses / entry['text_file']).read_bytes():
            raise RuntimeError('certifi 라이선스 원문과 동봉 소스가 일치하지 않습니다.')
        originals = {
            member.name[len(prefix + 'certifi/'):]: source.extractfile(member).read()
            for member in source.getmembers()
            if member.isfile() and member.name.startswith(prefix + 'certifi/')
        }
    # wheel은 upstream tests를 생략할 수 있다. 실행 코드와 인증서 데이터는 필수다.
    required = {name for name in originals if not name.startswith('tests/')}
    installed = {
        path.relative_to(package_dir).as_posix(): path.read_bytes()
        for path in package_dir.rglob('*')
        if path.is_file() and '__pycache__' not in path.parts
        and path.suffix not in ('.pyc', '.pyo')
    }
    if not required.issubset(installed) or any(
        name not in originals or content != originals[name]
        for name, content in installed.items()
    ):
        raise RuntimeError('설치된 certifi 코드 또는 인증서가 원본과 다릅니다. 수정 소스 제공 및 고지 갱신이 필요합니다.')


if __name__ == '__main__':
    import certifi

    verify_certifi(Path(__file__).resolve().parents[1], Path(certifi.__file__).parent,
                   importlib.metadata.version('certifi'))
    print('certifi 버전·원문·소스·인증서 일치 확인 완료')
