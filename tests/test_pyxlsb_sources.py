"""Offline sources, modified library acceptance, archive integrity and UI actions."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import tarfile
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pyxlsb
from maeumnarae.core import program_info

ROOT = Path(__file__).resolve().parents[1]
TOOLS = runpy.run_path(str(ROOT / 'packaging/prepare_pyxlsb_sources.py'))


class PyxlsbSources(unittest.TestCase):
    def setUp(self):
        self.entry = next(e for e in program_info.third_party_notices()['libraries'] if e['name'] == 'pyxlsb')
        self.package = Path(pyxlsb.__file__).parent

    def test_offline_archive_and_snapshot_match_current_sources(self):
        data = program_info.third_party_source(self.entry['source_file'])
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.entry['source_sha256'])
        snapshot = program_info.third_party_source(self.entry['modified_source_file'])
        with ZipFile(BytesIO(snapshot)) as archive:
            meta = json.loads(archive.read('CONTENTS.json'))
            self.assertEqual(meta['installed_version'], pyxlsb.__version__)
            for name, digest in meta['sha256'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest, name)
            for name in TOOLS['APP_FILES']:
                self.assertEqual(archive.read(name), (ROOT / name).read_bytes(), name)
            for path in self.package.rglob('*.py'):
                name = 'pyxlsb/' + path.relative_to(self.package).as_posix()
                self.assertEqual(archive.read(name), path.read_bytes(), name)
            with tarfile.open(ROOT / 'resources/licenses' / self.entry['source_file']) as upstream:
                prefix = 'pyxlsb-' + self.entry['version'] + '/'
                originals = {m.name[len(prefix):]: upstream.extractfile(m).read()
                             for m in upstream.getmembers()
                             if m.isfile() and m.name.startswith(prefix + 'pyxlsb/')}
            current = {n: archive.read(n) for n in archive.namelist() if n.startswith('pyxlsb/')}
            changed = sorted(n for n in originals.keys() | current.keys() if originals.get(n) != current.get(n))
            self.assertEqual(meta['changed_upstream_files'], changed)

    def test_modified_library_is_included_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / 'pyxlsb'
            shutil.copytree(self.package, package, ignore=shutil.ignore_patterns('__pycache__'))
            path = package / 'workbook.py'
            path.write_bytes(path.read_bytes() + b'\n# Local modification for source-offer test\n')
            _, content = TOOLS['source_bundle'](ROOT, package, '1.0.10+local')
            with ZipFile(BytesIO(content)) as archive:
                self.assertEqual(archive.read('pyxlsb/workbook.py'), path.read_bytes())
                meta = json.loads(archive.read('CONTENTS.json'))
                self.assertEqual(meta['installed_version'], '1.0.10+local')
                self.assertIn('pyxlsb/workbook.py', meta['changed_upstream_files'])
                self.assertIn(b'Local modification for source-offer test', archive.read('CHANGES.md'))
            with self.assertRaisesRegex(RuntimeError, '현재 코드와 다릅니다'):
                TOOLS['prepare'](ROOT, package, '1.0.10+local', check=True)

    def test_corrupted_reference_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'resources/licenses', root / 'resources/licenses')
            archive = root / 'resources/licenses' / self.entry['source_file']
            archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                TOOLS['source_bundle'](root, self.package, pyxlsb.__version__)

    def test_download_buttons_use_correct_file_and_media_type(self):
        from maeumnarae.views import about_view
        ui = MagicMock()
        with patch.object(about_view, 'ui', ui):
            about_view.build_about()
            calls = [c for c in ui.button.call_args_list if 'on_click' in c.kwargs]
            manifest = json.loads((ROOT / 'resources/licenses/manifest.json').read_text())
            sources = {
                Path(entry[field]).name: ROOT / 'resources/licenses' / entry[field]
                for entry in manifest['libraries']
                for field in ('source_file', 'modified_source_file')
                if entry.get(field)
            }
            self.assertEqual(len(calls), len(sources))
            for call in calls:
                call.kwargs['on_click']()
        downloads = ui.download.content.call_args_list
        self.assertTrue({'certifi-2026.7.22.tar.gz', 'pyxlsb-1.0.10.tar.gz',
                         'heartwings-xlsb-sources.zip'} <= sources.keys())
        self.assertEqual({c.args[1] for c in downloads}, sources.keys())
        for call in downloads:
            self.assertEqual(call.args[0], sources[call.args[1]].read_bytes())
            self.assertEqual(call.kwargs['media_type'],
                             'application/zip' if call.args[1].endswith('.zip') else 'application/gzip')

    def test_download_path_cannot_escape_license_folder(self):
        with self.assertRaises(ValueError):
            program_info.third_party_source('../../LICENSE')


if __name__ == '__main__':
    unittest.main()
