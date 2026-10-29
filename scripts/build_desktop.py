"""현재 OS/CPU의 독립 실행 앱을 빌드한다: python scripts/build_desktop.py."""

import ast
import argparse
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def find_iscc() -> Path:
    """명시 경로, PATH, 기본 설치 위치 순서로 Inno Setup을 찾는다."""
    explicit = os.environ.get('ISCC_PATH')
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
        raise RuntimeError(f'ISCC_PATH가 올바른 파일을 가리키지 않습니다: {explicit}')
    found = shutil.which('ISCC.exe')
    if found:
        return Path(found)
    for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        base = os.environ.get(variable)
        if base:
            folder = Path(base) / ('Programs/Inno Setup 6' if variable == 'LOCALAPPDATA' else 'Inno Setup 6')
            candidate = folder / 'ISCC.exe'
            if candidate.is_file():
                return candidate
    raise RuntimeError('Inno Setup 6.3 이상을 설치하세요: https://jrsoftware.org/isdl.php\n'
                       'ISCC.exe를 PATH에 추가하거나 ISCC_PATH 환경변수에 전체 경로를 지정하세요.')


def windows_metadata() -> tuple[str, str]:
    """앱 의존성을 import하지 않고 배포 메타데이터를 읽는다."""
    tree = ast.parse((ROOT / 'maeumnarae/core/program_info.py').read_text(encoding='utf-8'))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('PROGRAM_NAME', 'PROGRAM_VERSION'):
                    values[target.id] = ast.literal_eval(node.value)
    name, version = values['PROGRAM_NAME'], values['PROGRAM_VERSION']
    if not isinstance(name, str) or any(c in name for c in "\"'\r\n"):
        raise RuntimeError('설치 파일에 사용할 앱 이름이 올바르지 않습니다.')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?', version):
        raise RuntimeError('설치 파일 버전은 숫자로 된 major.minor.patch 형식이어야 합니다.')
    return name, version


def main() -> None:
    """macOS는 ZIP, Windows는 Inno Setup 설치 파일까지 생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-only', action='store_true',
                        help='실행 파일 없이 현재 환경의 소스 자료만 생성 (미검증으로 표시)')
    args = parser.parse_args()
    name, version = windows_metadata()
    iscc = None
    installer_version = None
    if sys.platform == 'win32' and not args.sources_only:
        if struct.calcsize('P') != 8 or platform.machine().lower() not in ('amd64', 'x86_64'):
            raise RuntimeError('Windows 설치 파일은 x64 환경의 x64 Python으로 빌드해야 합니다.')
        iscc = find_iscc()
        details = subprocess.run([str(iscc), '/?'], capture_output=True, text=True,
                                 errors='replace', check=False)
        match = re.search(r'Inno Setup\s+(\d+\.\d+\.\d+)', details.stdout + details.stderr)
        installer_version = match[1] if match else 'unidentified; retain installed compiler version with release'
    import pyxlsb
    source_tools = runpy.run_path(str(ROOT / 'packaging/prepare_pyxlsb_sources.py'))
    source_tools['prepare'](ROOT, Path(pyxlsb.__file__).parent, pyxlsb.__version__)
    release = runpy.run_path(str(ROOT / 'packaging/release_sources.py'))
    inputs = release['collect_inputs'](ROOT)
    build_environment = release['environment']()
    if args.sources_only:
        source = release['write_release'](ROOT, version, inputs, build_environment, [],
                                          output_dir=ROOT / 'dist/source-preview')
        print(f'소스 자료 생성 (실행 파일 검증 전): {source}')
        return
    environment = dict(os.environ)
    environment['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'build' / 'pyinstaller-cache')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    str(ROOT / 'packaging' / 'maeumnarae.spec')], cwd=ROOT, env=environment, check=True)
    artifacts = []
    if iscc is not None:
        subprocess.run([str(iscc), f'/DAppName={name}', f'/DAppVersion={version}',
                        f'/DSourceRoot={ROOT}', str(ROOT / 'packaging' / 'maeumnarae.iss')],
                       cwd=ROOT, check=True)
        print(f'설치 파일: {ROOT / "dist" / "installer" / f"maeumnarae-{version}-windows-x64-setup.exe"}')
        artifacts.append(ROOT / 'dist/installer' / f'maeumnarae-{version}-windows-x64-setup.exe')
    elif sys.platform == 'darwin':
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(ROOT / 'dist' / '마음나래.app'), str(ROOT / 'dist' / 'maeumnarae-macos.zip')], check=True)
        artifacts.append(ROOT / 'dist/maeumnarae-macos.zip')
    else:
        archive = shutil.make_archive(str(ROOT / 'dist' / f'maeumnarae-{version}-linux-{platform.machine()}'),
                                      'gztar', root_dir=ROOT / 'dist', base_dir='maeumnarae')
        artifacts.append(Path(archive))
    if release['hashes'](inputs) != release['hashes'](release['collect_inputs'](ROOT)):
        raise RuntimeError('빌드 중 소스/리소스가 변경되었습니다. 다시 빌드해 대응 소스를 생성하세요.')
    if build_environment != release['environment']():
        raise RuntimeError('빌드 중 Python 환경이 변경되었습니다. 다시 빌드하세요.')
    source = release['write_release'](ROOT, version, inputs, build_environment, artifacts,
                                      installer_version=installer_version)
    print(f'설치 파일과 함께 제공할 소스 자료: {source}')
    print(f'빌드 완료: {ROOT / "dist"}')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'빌드 실패: {exc}', file=sys.stderr)
        sys.exit(1)
