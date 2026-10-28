# 각 대상 OS/CPU의 가상환경에서 빌드한다. 사용자 DB/로그는 절대 포함하지 않는다.
import sys
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parent
app_icon = root / 'resources' / 'icons' / ('icon.icns' if sys.platform == 'darwin' else 'icon.ico')
datas = [(str(Path(nicegui.__file__).parent), 'nicegui')]
datas += [(str(root / 'resources'), 'resources'), (str(root / 'LICENSE'), '.')]
datas += collect_data_files('webview')
datas += collect_data_files('holidays')
datas += copy_metadata('holidays')
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
splash_targets = []
splash_binaries = []
if sys.platform == 'win32':
    splash = Splash(str(root / 'resources' / 'icons' / 'splash.png'),
                    binaries=a.binaries, datas=a.datas, text_pos=None,
                    minify_script=True, always_on_top=False)
    splash_targets = [splash]
    splash_binaries = splash.binaries
exe = EXE(pyz, a.scripts, *splash_targets, [], exclude_binaries=True, name='maeumnarae', console=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, icon=str(app_icon))
coll = COLLECT(exe, a.binaries, a.datas, splash_binaries, name='maeumnarae')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='마음나래.app', bundle_identifier='org.maeumnarae.desktop',
                 icon=str(app_icon),
                 info_plist={'CFBundleName': '마음나래', 'CFBundleDisplayName': '마음나래',
                             'CFBundleShortVersionString': '0.5.0', 'CFBundleVersion': '5',
                             'NSHighResolutionCapable': True})
