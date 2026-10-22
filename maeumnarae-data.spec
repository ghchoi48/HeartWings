# 1단계 CLI 배포용. 각 대상 OS/CPU에서 별도 빌드한다.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
data, binaries, hidden = collect_all('sqlcipher3')
model_data, model_binaries, model_hidden = collect_all('pydantic')
a = Analysis(
    [str(root / 'init_db.py')], pathex=[str(root)],
    binaries=binaries + model_binaries,
    datas=data + model_data + [(str(root / 'LICENSE'), '.'), (str(root / 'licenses'), 'licenses')],
    hiddenimports=hidden + model_hidden + [
        'sqlcipher3.dbapi2', 'sqlcipher3._sqlite3',
        'repositories.student_repo', 'repositories.counseling_repo',
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='maeumnarae-data', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='maeumnarae-data')
