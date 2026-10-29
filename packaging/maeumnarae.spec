# 각 대상 OS/CPU의 가상환경에서 빌드한다. 사용자 DB/로그는 절대 포함하지 않는다.
import sys
import runpy
from pathlib import Path

import nicegui
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parent
_, app_version = runpy.run_path(str(root / 'scripts/build_desktop.py'))['windows_metadata']()
runpy.run_path(str(root / 'packaging' / 'verify_certifi.py'), run_name='__main__')
import pyxlsb
source_tools = runpy.run_path(str(root / 'packaging' / 'prepare_pyxlsb_sources.py'))
source_tools['prepare'](root, Path(pyxlsb.__file__).parent, pyxlsb.__version__)
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
                             'CFBundleShortVersionString': app_version, 'CFBundleVersion': app_version,
                             'NSHighResolutionCapable': True})
