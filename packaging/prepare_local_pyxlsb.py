"""Create an editable, pip-installable pyxlsb tree from the bundled used sources.

python packaging/prepare_local_pyxlsb.py [--output build/pyxlsb-local]
Existing output is never overwritten. Installation is a separate explicit command.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def prepare(root: Path, output: Path) -> Path:
    if output.exists():
        raise RuntimeError('대상 폴더가 이미 있습니다. 수정본 보호를 위해 다른 --output 경로를 지정하세요.')
    license_root = root / 'resources/licenses'
    manifest = json.loads((license_root / 'manifest.json').read_text(encoding='utf-8'))
    entry = next(e for e in manifest['libraries'] if e['name'] == 'pyxlsb')
    files = {}
    with ZipFile(license_root / entry['modified_source_file']) as archive:
        contents = json.loads(archive.read('CONTENTS.json'))
        for name, digest in contents['sha256'].items():
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError(f'동봉 소스의 해시가 다릅니다: {name}')
            if name.startswith('pyxlsb/'):
                parts = PurePosixPath(name)
                if '..' in parts.parts or '\\' in name or ':' in name:
                    raise RuntimeError('소스 경로가 올바르지 않습니다.')
                files[name] = data
        for name in ('COPYING', 'COPYING.LESSER'):
            files[name] = archive.read('resources/licenses/pyxlsb/' + name)
        files['CHANGES.md'] = archive.read('CHANGES.md')
    if 'pyxlsb/__init__.py' not in files:
        raise RuntimeError('pyxlsb 소스가 없습니다.')
    # Packaging for editable source modifications, without downloading a build backend.
    files['setup.py'] = b'''from pathlib import Path
import ast
from setuptools import setup, find_packages
module = ast.parse(Path("pyxlsb/__init__.py").read_text(encoding="utf-8"))
version = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
setup(name="pyxlsb", version=version, packages=find_packages(),
      include_package_data=True, license="LGPLv3+", license_files=["COPYING", "COPYING.LESSER"])
'''
    files['MANIFEST.in'] = b'recursive-include pyxlsb *\ninclude COPYING COPYING.LESSER CHANGES.md\n'
    output.mkdir(parents=True)
    for name, data in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/pyxlsb-local'))
    args = parser.parse_args()
    print(prepare(Path(__file__).resolve().parents[1], args.output))
