# 각 대상 OS/CPU의 가상환경에서 빌드한다. 사용자 DB/로그는 절대 포함하지 않는다.
import sys
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH)
datas = [(str(Path(nicegui.__file__).parent), 'nicegui')]
datas += collect_data_files('webview')
datas += copy_metadata('nicegui') + copy_metadata('pywebview')
datas += copy_metadata('sqlcipher3')
binaries = collect_dynamic_libs('sqlcipher3')
hidden = ['sqlcipher3.dbapi2', 'sqlcipher3._sqlite3', 'webview', 'webview.dom',
          'nicegui.native.native_mode', 'multiprocessing', 'uvicorn.logging']
if sys.platform == 'darwin':
    hidden += ['webview.platforms.cocoa', 'AppKit', 'Foundation', 'WebKit', 'objc', 'Quartz', 'Security']
elif sys.platform == 'win32':
    hidden += ['webview.platforms.winforms', 'webview.platforms.edgechromium']
else:
    hidden += ['webview.platforms.gtk', 'gi']

a = Analysis([str(root / 'main.py')], pathex=[str(root)], datas=datas, binaries=binaries,
             hiddenimports=hidden, excludes=['pytest', 'playwright', 'nicegui.testing'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='maeumnarae', console=False,
          argv_emulation=False, target_arch=None, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name='maeumnarae')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='마음나래.app', bundle_identifier='org.maeumnarae.desktop',
                 info_plist={'CFBundleName': '마음나래', 'CFBundleDisplayName': '마음나래',
                             'CFBundleShortVersionString': '0.5.0', 'CFBundleVersion': '5',
                             'NSHighResolutionCapable': True})
