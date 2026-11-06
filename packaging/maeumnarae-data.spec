# 1단계 CLI 배포용. 각 대상 OS/CPU에서 별도 빌드한다.
from pathlib import Path
import runpy
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
runpy.run_path(str(root / 'packaging' / 'verify_certifi.py'), run_name='__main__')
import pyxlsb
source_tools = runpy.run_path(str(root / 'packaging' / 'prepare_pyxlsb_sources.py'))
source_tools['prepare'](root, Path(pyxlsb.__file__).parent, pyxlsb.__version__)
data, binaries, hidden = collect_all('sqlcipher3')
model_data, model_binaries, model_hidden = collect_all('pydantic')
a = Analysis(
    [str(root / 'init_db.py')], pathex=[str(root)],
    binaries=binaries + model_binaries,
    datas=data + model_data + [(str(root / 'LICENSE'), '.'), (str(root / 'resources' / 'licenses'), 'resources/licenses')],
    hiddenimports=hidden + model_hidden + [
        'sqlcipher3.dbapi2', 'sqlcipher3._sqlite3',
        'maeumnarae.repositories.students.student_repo', 'maeumnarae.repositories.journals.counseling_repo',
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='maeumnarae-data', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='maeumnarae-data')
