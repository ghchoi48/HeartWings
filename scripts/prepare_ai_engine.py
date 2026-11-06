"""고정된 공식 엔진을 검증·준비한다. python scripts/prepare_ai_engine.py [--verify]"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def target_platform():
    machine = platform.machine().lower()
    if sys.platform == 'darwin' and machine in {'arm64', 'aarch64'}:
        return 'macos-arm64'
    if sys.platform == 'win32' and machine in {'amd64', 'x86_64'}:
        return 'windows-x64'
    return None


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(root=ROOT, target=None):
    target = target or target_platform()
    if target is None:
        return []
    manifest = json.loads((root / 'resources/ai/engines.json').read_text())
    folder = root / 'resources/ai/runtime' / target
    try:
        stamp = json.loads((folder / 'verified.json').read_text())
        if stamp['version'] != manifest['version'] or stamp['archive_sha256'] != manifest['platforms'][target]['sha256']:
            raise ValueError()
        executable = 'llama-server.exe' if target == 'windows-x64' else 'llama-server'
        if executable not in stamp['files']:
            raise ValueError()
        for name, digest in stamp['files'].items():
            if Path(name).name != name or sha256(folder / name) != digest:
                raise ValueError()
        return [(str(folder / name), f'resources/ai/runtime/{target}') for name in stamp['files']]
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('AI 엔진 누락 또는 검증 실패: python scripts/prepare_ai_engine.py 를 실행하세요.') from None


def prepare(target):
    import httpx
    manifest = json.loads((ROOT / 'resources/ai/engines.json').read_text())
    entry = manifest['platforms'][target]
    destination = ROOT / 'resources/ai/runtime' / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        temp = Path(temp)
        archive = temp / 'archive'
        with httpx.stream('GET', entry['url'], follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            with archive.open('wb') as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    stream.write(chunk)
        if sha256(archive) != entry['sha256']:
            raise RuntimeError('공식 엔진 아카이브 체크섬 불일치')
        unpacked = temp / 'unpacked'
        unpacked.mkdir()
        if entry['url'].endswith('.zip'):
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    if not (unpacked / member.filename).resolve().is_relative_to(unpacked):
                        raise RuntimeError('안전하지 않은 ZIP 경로')
                source.extractall(unpacked)
        else:
            with tarfile.open(archive) as source:
                source.extractall(unpacked, filter='data')
        staged = temp / 'staged'
        staged.mkdir()
        executable = 'llama-server.exe' if target == 'windows-x64' else 'llama-server'
        for source in unpacked.rglob('*'):
            if source.is_file() and (source.name == executable or source.suffix in {'.dll', '.dylib', '.metal'}):
                output = staged / source.name
                if output.exists() and sha256(output) != sha256(source):
                    raise RuntimeError('동일 이름의 서로 다른 엔진 라이브러리')
                shutil.copy2(source, output)
        if not (staged / executable).is_file():
            raise RuntimeError('아카이브에 llama-server가 없습니다.')
        (staged / executable).chmod(0o755)
        stamp = {'version': manifest['version'], 'archive_sha256': entry['sha256'],
                 'files': {p.name: sha256(p) for p in staged.iterdir()}}
        (staged / 'verified.json').write_text(json.dumps(stamp, indent=2) + '\n')
        if destination.exists():
            shutil.rmtree(destination)
        staged.replace(destination)
    verify(target=target)
    print(f'AI 엔진 준비 완료: {target}, {manifest["version"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--platform', choices=['macos-arm64', 'windows-x64'], default=target_platform())
    args = parser.parse_args()
    if args.platform is None:
        parser.error('지원되는 엔진 대상 플랫폼을 지정해 주세요.')
    if args.verify:
        verify(target=args.platform)
    else:
        prepare(args.platform)
