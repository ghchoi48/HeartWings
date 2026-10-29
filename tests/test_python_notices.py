"""The notice audit must reject missing, stale and altered notice material."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
API = runpy.run_path(str(ROOT / 'packaging/audit_python_notices.py'))


class PythonNotices(unittest.TestCase):
    def test_committed_inventory_and_offline_sources(self):
        root = ROOT / 'resources/licenses'
        report = json.loads((root / 'PYTHON_BUNDLE_INVENTORY.json').read_text())
        API['verify'](root, report)
        from maeumnarae.core.program_info import third_party_notices, third_party_source
        entries = {API['normalized'](e['name']): e for e in third_party_notices()['libraries']}
        for name in report['packages']:
            self.assertTrue(entries[name]['text'].strip(), name)
        for name in ('bidict', 'orjson'):
            entry = entries[name]
            self.assertEqual(API['sha256'](third_party_source(entry['source_file'])), entry['source_sha256'])

    def test_missing_stale_and_tampered_notices_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'Example copyright and license\n'
            (root / 'license.txt').write_bytes(data)
            entry = {'name': 'example', 'version': '1.0', 'text_file': 'license.txt',
                     'license_sha256': API['sha256'](data)}
            report = {'packages': {'example': {'version': '1.0'}}}
            def save(entries):
                (root / 'manifest.json').write_text(json.dumps({'libraries': entries}))
            save([])
            with self.assertRaises(KeyError):
                API['verify'](root, report)
            save([dict(entry, version='0.9')])
            with self.assertRaisesRegex(ValueError, 'version'):
                API['verify'](root, report)
            save([entry])
            (root / 'license.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash'):
                API['verify'](root, report)


if __name__ == '__main__':
    unittest.main()
