"""현재 OS/CPU의 독립 실행 앱을 빌드한다: python scripts/build_desktop.py."""

import ast
import os
from pathlib import Path
import platform
import re
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
    iscc = None
    if sys.platform == 'win32':
        if struct.calcsize('P') != 8 or platform.machine().lower() not in ('amd64', 'x86_64'):
            raise RuntimeError('Windows 설치 파일은 x64 환경의 x64 Python으로 빌드해야 합니다.')
        iscc = find_iscc()
        name, version = windows_metadata()
    environment = dict(os.environ)
    environment['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'build' / 'pyinstaller-cache')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    str(ROOT / 'packaging' / 'maeumnarae.spec')], cwd=ROOT, env=environment, check=True)
    if iscc is not None:
        subprocess.run([str(iscc), f'/DAppName={name}', f'/DAppVersion={version}',
                        f'/DSourceRoot={ROOT}', str(ROOT / 'packaging' / 'maeumnarae.iss')],
                       cwd=ROOT, check=True)
        print(f'설치 파일: {ROOT / "dist" / "installer" / f"maeumnarae-{version}-windows-x64-setup.exe"}')
    elif sys.platform == 'darwin':
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(ROOT / 'dist' / '마음나래.app'), str(ROOT / 'dist' / 'maeumnarae-macos.zip')], check=True)
    print(f'빌드 완료: {ROOT / "dist"}')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'빌드 실패: {exc}', file=sys.stderr)
        sys.exit(1)
