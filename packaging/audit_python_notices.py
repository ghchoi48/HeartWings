"""Audit Python notices against a macOS PyInstaller ZIP (no app execution).

Use the build's Python environment so importlib's module-to-distribution mapping
matches the artifact. This is not a native-library or web-asset inventory.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import tempfile
import zipfile


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inventory(archive, release):
    from PyInstaller.archive.readers import CArchiveReader

    recorded = json.loads(release.read_text())
    digest = sha256(archive.read_bytes())
    if recorded['artifacts_sha256'].get(archive.name) != digest:
        raise ValueError('Artifact does not match release JSON')
    evidence = {}
    with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory() as tmp:
        names = [n for n in bundle.namelist() if not n.startswith('__MACOSX/')]
        executable = next(n for n in names if n.endswith('/Contents/MacOS/maeumnarae'))
        path = Path(tmp) / 'maeumnarae'
        path.write_bytes(bundle.read(executable))
        reader = CArchiveReader(str(path))
        for module in reader.open_embedded_archive('PYZ.pyz').toc:
            evidence.setdefault(module.split('.')[0], []).append('PYZ:' + module)
        for name in names:
            for prefix in ('/Contents/Frameworks/', '/Contents/Resources/'):
                if prefix in name and name.endswith(('.so', '.py')):
                    relative = name.split(prefix, 1)[1]
                    top = relative.split('/')[0].split('.')[0]
                    evidence.setdefault(top, []).append('bundle:' + relative)
    mapping = metadata.packages_distributions()
    packages = {}
    for top, entries in sorted(evidence.items()):
        for name in mapping.get(top, []):
            key = normalized(name)
            dist = metadata.distribution(name)
            version = recorded['environment']['packages'].get(key)
            # Validation builds intentionally replace pyxlsb with a local version.
            if version != dist.version and not (key == 'pyxlsb' and version == dist.version + '+heartwings.validation'):
                raise ValueError(f'{name}: installed {dist.version}, recorded {version}')
            item = packages.setdefault(key, {'name': name, 'version': version, 'evidence': []})
            item['evidence'].extend(sorted(set(entries)))
    return {'artifact': archive.name, 'artifact_sha256': digest,
            'release_sha256': sha256(release.read_bytes()),
            'scope': 'Python packages mapped from PYZ modules and bundled .so/.py files; excludes native/web assets',
            'packages': dict(sorted(packages.items()))}


def verify(root, report):
    manifest = json.loads((root / 'manifest.json').read_text())
    entries = {normalized(e['name']): e for e in manifest['libraries']}
    for key, package in report['packages'].items():
        e = entries[key]
        actual = package['version']
        if e.get('version') != actual and not (key == 'pyxlsb' and actual == e.get('version', '') + '+heartwings.validation'):
            raise ValueError(f'{key}: notice version does not match artifact')
        text = (root / e['text_file']).read_bytes()
        if not text.strip():
            raise ValueError(f'{key}: empty notice')
        if 'license_sha256' in e and sha256(text) != e['license_sha256']:
            raise ValueError(f'{key}: notice hash mismatch')
        for f in e.get('license_files', []):
            if sha256((root / f['file']).read_bytes()) != f['sha256']:
                raise ValueError(f'{key}: original notice hash mismatch: {f["file"]}')
        if e.get('source_file') and sha256((root / e['source_file']).read_bytes()) != e['source_sha256']:
            raise ValueError(f'{key}: source hash mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inventory(args.archive, args.release)
    verify(Path(__file__).resolve().parents[1] / 'resources/licenses', report)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS: {len(report["packages"])} bundled Python distributions have notices')


if __name__ == '__main__':
    main()
