"""현재 OS/CPU의 독립 실행 앱을 빌드한다: python scripts/build_desktop.py."""

import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    """작업 폴더 안에 빌드 캐시/결과를 저장한다. macOS에서는 .app을 ZIP으로도 제공한다."""
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment['PYINSTALLER_CONFIG_DIR'] = str(root / 'build' / 'pyinstaller-cache')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    str(root / 'packaging' / 'maeumnarae.spec')], cwd=root, env=environment, check=True)
    if sys.platform == 'darwin':
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(root / 'dist' / '마음나래.app'), str(root / 'dist' / 'maeumnarae-macos.zip')], check=True)
    print(f'빌드 완료: {root / "dist"}')


if __name__ == '__main__':
    main()
