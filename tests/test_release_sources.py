"""Release source coverage, exclusion policy and modified pyxlsb preparation."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = runpy.run_path(str(ROOT / 'packaging/release_sources.py'))
LOCAL = runpy.run_path(str(ROOT / 'packaging/prepare_local_pyxlsb.py'))


class ReleaseSources(unittest.TestCase):
    def test_source_collection_includes_uncommitted_inputs_excludes_private_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in RELEASE['TOP_FILES']:
                (root / name).write_text('source')
            for folder in RELEASE['SOURCE_ROOTS']:
                (root / folder).mkdir()
            for name in ['maeumnarae/new_uncommitted.py', 'resources/font.ttf', 'tests/check.py',
                         'resources/.env', 'resources/test.db', 'resources/test.db-wal',
                         'resources/signing.key', 'maeumnarae/__pycache__/module.pyc']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test')
            files = RELEASE['collect_inputs'](root)
            for name in ['maeumnarae/new_uncommitted.py', 'resources/font.ttf', 'tests/check.py']:
                self.assertIn(name, files)
            for name in ['resources/.env', 'resources/test.db', 'resources/test.db-wal',
                         'resources/signing.key', 'maeumnarae/__pycache__/module.pyc']:
                self.assertNotIn(name, files)
            (root / 'resources/link').symlink_to(root / 'README.md')
            with self.assertRaisesRegex(RuntimeError, '심볼릭 링크'):
                RELEASE['collect_inputs'](root)

    def test_paired_archive_records_exact_binary_source_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / 'app.zip'
            artifact.write_bytes(b'binary fixture')
            env = {'os': 'Windows', 'machine': 'AMD64', 'packages': {'pyxlsb': '1.0.10', 'pydantic': '2.14.1'}}
            files = {'main.py': b'print("source")', 'BUILDING.md': b'build instructions'}
            source = RELEASE['write_release'](root, '1.1.0', files, env, [artifact], installer_version='6.7.3')
            with ZipFile(source) as archive:
                self.assertEqual(archive.read('main.py'), files['main.py'])
                metadata = json.loads(archive.read('release/build-environment.json'))
                self.assertEqual(metadata['status'], 'paired-build')
                self.assertEqual(metadata['artifacts_sha256']['app.zip'], hashlib.sha256(artifact.read_bytes()).hexdigest())
                pins = archive.read('release/requirements-rebuild.txt').decode()
                self.assertNotIn('pyxlsb==', pins)
                self.assertIn('pydantic==2.14.1', pins)
            sidecar = next(source.parent.glob('*-release.json'))
            self.assertEqual(json.loads(sidecar.read_text())['source_archive_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual((source.parent / artifact.name).read_bytes(), artifact.read_bytes())

    def test_sources_only_is_not_claimed_as_a_binary_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = RELEASE['write_release'](Path(tmp), '1.1.0', {},
                       {'os': 'Darwin', 'machine': 'arm64', 'packages': {}}, [])
            with ZipFile(source) as archive:
                info = json.loads(archive.read('release/build-environment.json'))
                self.assertEqual(info['status'], 'source-only-unverified')
                self.assertEqual(info['artifacts_sha256'], {})

    def test_environment_uses_effective_distribution_version(self):
        records = [SimpleNamespace(metadata={'Name': 'pyxlsb'}, version='1.0.10+local'),
                   SimpleNamespace(metadata={'Name': 'pyxlsb'}, version='1.0.10')]
        with patch('importlib.metadata.distributions', return_value=records), \
             patch('importlib.metadata.version', return_value='1.0.10+local'):
            self.assertEqual(RELEASE['environment']()['packages']['pyxlsb'], '1.0.10+local')

    def test_local_source_preserves_used_files_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = LOCAL['prepare'](ROOT, Path(tmp) / 'local')
            with ZipFile(ROOT / 'resources/licenses/sources/heartwings-xlsb-sources.zip') as archive:
                self.assertEqual((output / 'pyxlsb/workbook.py').read_bytes(), archive.read('pyxlsb/workbook.py'))
            self.assertTrue((output / 'COPYING.LESSER').is_file())
            self.assertTrue((output / 'setup.py').is_file())
            (output / 'pyxlsb/workbook.py').write_text('# user modification')
            with self.assertRaisesRegex(RuntimeError, '수정본 보호'):
                LOCAL['prepare'](ROOT, output)
            self.assertEqual((output / 'pyxlsb/workbook.py').read_text(), '# user modification')


if __name__ == '__main__':
    unittest.main()
