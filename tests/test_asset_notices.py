"""Native/web notice evidence must fail closed on missing or altered material."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
API = runpy.run_path(str(ROOT / 'packaging/audit_asset_notices.py'))


class AssetNotices(unittest.TestCase):
    def test_committed_evidence_and_font_names(self):
        report = API['verify'](ROOT / 'resources/licenses')
        derivatives = [a for p, a in report['assets'].items()
                       if 'JournalSans-' in p or 'HeartWingsRidiBatang-' in p]
        self.assertEqual(len(derivatives), 3)
        for asset in derivatives:
            for name in asset['font_names']['1'] + asset['font_names']['16']:
                self.assertTrue(name.startswith('HeartWings '))
            self.assertTrue(asset['font_names']['0'])  # original copyright preserved

    def test_missing_mapping_and_modified_text_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = b'Copyright and license material\n'
            (root / 'notice.txt').write_bytes(text)
            entry = {'name': 'example', 'asset_audit': True, 'text_file': 'notice.txt',
                     'license_sha256': API['digest'](text), 'license_files': []}
            (root / 'manifest.json').write_text(json.dumps({'libraries': [entry], 'fonts': []}))
            report = {'assets': {'asset.js': {'notices': ['missing']}}, 'evidence_files': []}
            path = root / 'ASSET_INVENTORY.json'
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'Missing notice'):
                API['verify'](root)
            report['assets']['asset.js']['notices'] = ['example']
            path.write_text(json.dumps(report))
            (root / 'notice.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Hash mismatch'):
                API['verify'](root)

    def test_snapshot_finds_native_and_web_assets_not_macos_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bundle.zip'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('App.app/Contents/Frameworks/libcrypto.3.dylib', b'native')
                z.writestr('App.app/Contents/Resources/nicegui/static/vue.js', b'web')
                z.writestr('__MACOSX/App.app/Contents/Resources/nicegui/static/._vue.js', b'metadata')
            snapshot = API['snapshot'](p)
            self.assertEqual(len(snapshot), 2)
            self.assertEqual({a['kind'] for a in snapshot.values()}, {'native', 'web'})


if __name__ == '__main__':
    unittest.main()
