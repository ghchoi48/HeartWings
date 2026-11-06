"""Collect reviewable build inputs and emit an OS-specific source release.

No git checkout or remote access is needed. Only declared source/resource roots
are included; credentials, caches, user databases and build outputs are excluded.
"""
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

TOP_FILES = ('LICENSE', 'README.md', 'BUILDING.md', 'main.py', 'init_db.py', '.gitignore', '.gitattributes')
SOURCE_ROOTS = ('maeumnarae', 'packaging', 'scripts', 'requirements', 'tests', 'resources')
EXCLUDED_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.aws', '.codex', '.agents', 'node_modules'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.db', '.sqlite', '.sqlite3', '.log', '.tmp', '.bak', '.pem', '.key', '.p12', '.pfx'}


def collect_inputs(root: Path) -> dict[str, bytes]:
    files = {}
    for name in TOP_FILES:
        path = root / name
        if path.is_symlink():
            raise RuntimeError(f'소스 묶음에 심볼릭 링크를 포함할 수 없습니다: {name}')
        files[name] = path.read_bytes()
    for folder in SOURCE_ROOTS:
        for path in sorted((root / folder).rglob('*')):
            relative = path.relative_to(root)
            if path.is_relative_to(root / 'resources/ai/runtime'):
                continue  # 고정 아카이브에서 준비하는 실행 바이너리는 소스가 아니다.
            if any(part in EXCLUDED_DIRS or part.startswith('.') for part in relative.parts[1:]):
                continue
            if path.is_symlink():
                raise RuntimeError(f'소스 묶음에 심볼릭 링크를 포함할 수 없습니다: {relative}')
            if not path.is_file() or path.suffix.lower() in EXCLUDED_SUFFIXES or '.db-' in path.name:
                continue
            files[relative.as_posix()] = path.read_bytes()
    return files


def environment() -> dict:
    packages = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get('Name')
        if name and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
            # Resolve by importlib's effective search order: a venv override must
            # not be overwritten by a later system-site-packages distribution.
            normalized = re.sub(r'[-_.]+', '-', name).lower()
            if normalized not in packages:
                packages[normalized] = metadata.version(name)
    native = {'python_openssl': ssl.OPENSSL_VERSION}
    try:
        from sqlcipher3 import dbapi2
        with dbapi2.connect(':memory:') as connection:
            row = connection.execute('PRAGMA cipher_version').fetchone()
            native['sqlcipher_engine'] = row[0] if row else 'unavailable'
            native['sqlite'] = dbapi2.sqlite_version
    except (ImportError, OSError) as error:
        native['sqlcipher_engine'] = f'unavailable ({type(error).__name__})'
    if shutil.which('pkg-config'):
        for package in ('sqlcipher', 'gtk+-3.0', 'webkit2gtk-4.1', 'webkit2gtk-4.0'):
            try:
                result = subprocess.run(['pkg-config', '--modversion', package],
                                        capture_output=True, text=True, timeout=5, check=False)
                if result.returncode == 0:
                    native['pkg-config:' + package] = result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
    return {
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'os': platform.system(), 'os_release': platform.release(), 'machine': platform.machine(),
        'pointer_bits': 64 if sys.maxsize > 2**32 else 32,
        'packages': dict(sorted(packages.items())),
        'native_versions': native,
        'native_dependencies': 'See BUILDING.md; Python metadata does not capture system libraries or installer tools.',
    }


def hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}


def write_release(root: Path, version: str, files: dict[str, bytes], env: dict,
                  artifacts: list[Path], *, output_dir: Path | None = None,
                  installer_version: str | None = None) -> Path:
    """Source-only exports are explicitly unpaired; successful builds supply artifacts."""
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('잘못된 앱 버전입니다.')
    target = re.sub(r'[^a-z0-9-]', '-', f"{env['os']}-{env['machine']}".lower())
    output = output_dir or root / 'dist/release'
    output.mkdir(parents=True, exist_ok=True)
    basename = f'maeumnarae-{version}-{target}'
    binary_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts}
    info = {
        'app_version': version, 'target': target,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'paired-build' if artifacts else 'source-only-unverified',
        'artifacts_sha256': binary_hashes, 'source_files_sha256': hashes(files),
        'environment': env, 'inno_setup_version': installer_version,
        'scope': 'Application build inputs and bundled LGPL/MPL sources; not an offline mirror of every dependency.',
    }
    payload = dict(files)
    payload['release/build-environment.json'] = (json.dumps(info, ensure_ascii=False, indent=2) + '\n').encode()
    # Never overwrite an intentionally modified local pyxlsb during dependency setup.
    pins = [f'{name}=={value}' for name, value in env['packages'].items() if name != 'pyxlsb']
    payload['release/requirements-rebuild.txt'] = (
        '# Exact observed Python environment for this OS/CPU; install local pyxlsb LAST.\n'
        + '\n'.join(pins) + '\n').encode()
    source_zip = output / (basename + '-sources.zip')
    with ZipFile(source_zip, 'w') as archive:
        for name, data in sorted(payload.items()):
            member = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            member.compress_type = ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            archive.writestr(member, data)
    # Sidecar links the exact source archive to this build's downloadable binaries.
    info['source_archive_sha256'] = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    info['source_archive'] = source_zip.name
    (output / (basename + '-release.json')).write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for artifact in artifacts:
        destination = output / artifact.name
        if artifact.resolve() != destination.resolve():
            shutil.copyfile(artifact, destination)
    return source_zip
