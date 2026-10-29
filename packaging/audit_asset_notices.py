"""Check recorded macOS native/web/font assets and their bundled notices.

This verifies evidence and material integrity, not legal clearance or exact
linker reachability of every component in upstream locks and wheel SBOMs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WEB_SUFFIXES = {'.js', '.mjs', '.css', '.woff', '.woff2', '.ttf', '.otf', '.svg',
                '.png', '.jpg', '.jpeg', '.ico', '.wasm', '.json'}
FONT_SUFFIXES = {'.ttf', '.otf', '.woff', '.woff2'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(archive):
    result = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename
            if name.startswith('__MACOSX/') or '/Contents/' not in name or info.is_dir():
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                continue  # The actual target file is inventoried separately.
            path = name.split('/Contents/', 1)[1]
            suffix = Path(path).suffix.lower()
            if path.startswith('Resources/nicegui/') and suffix in WEB_SUFFIXES:
                kind = 'web'
            elif path.startswith('Resources/resources/fonts/') and suffix in FONT_SUFFIXES:
                kind = 'font'
            elif (path.startswith('Frameworks/') and suffix in {'.dylib', '.so'}) or path.endswith('/Versions/3.14/Python') or path == 'MacOS/maeumnarae':
                kind = 'native'
            else:
                continue
            result[path] = {'kind': kind, 'sha256': digest(bundle.read(info))}
    return dict(sorted(result.items()))


def checked_file(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes license directory: {relative}')
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f'Hash mismatch: {relative}')
    return data


def verify(root, archive=None):
    inventory = json.loads((root / 'ASSET_INVENTORY.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    entries = {e['name']: e for category in ('libraries', 'fonts') for e in manifest[category]}
    for asset in inventory['assets'].values():
        if not asset['notices']:
            raise ValueError('Asset has no notice mapping')
        for name in asset['notices']:
            if name not in entries:
                raise ValueError(f'Missing notice: {name}')
    for entry in entries.values():
        if not entry.get('asset_audit'):
            continue
        checked_file(root, entry['text_file'], entry['license_sha256']).decode('utf-8')
        for record in entry['license_files']:
            checked_file(root, record['file'], record['sha256'])
        if entry.get('source_file'):
            checked_file(root, entry['source_file'], entry['source_sha256'])
    for record in inventory['evidence_files']:
        checked_file(root, record['file'], record['sha256'])
    # Also verify pre-existing notices referenced by the new inventory.
    for name in {n for a in inventory['assets'].values() for n in a['notices']}:
        entry = entries[name]
        data = (root / entry['text_file']).read_bytes()
        if not data.strip():
            raise ValueError(f'Empty notice: {name}')
        if entry.get('license_sha256') and digest(data) != entry['license_sha256']:
            raise ValueError(f'Hash mismatch: {name}')
    if archive is not None:
        if digest(archive.read_bytes()) != inventory['artifact_sha256']:
            raise ValueError('Artifact differs from audited ZIP; create a new audit')
        actual = snapshot(archive)
        expected = {p: {'kind': a['kind'], 'sha256': a['sha256']} for p, a in inventory['assets'].items()}
        if actual != expected:
            raise ValueError('Asset set or asset content differs from inventory')
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Original audited macOS ZIP; optional offline evidence check otherwise')
    args = parser.parse_args()
    report = verify(ROOT / 'resources/licenses', args.archive)
    counts = {k: sum(a['kind'] == k for a in report['assets'].values()) for k in ('native', 'web', 'font')}
    print('PASS: asset hashes, notice mappings and collected materials:', counts)


if __name__ == '__main__':
    main()
