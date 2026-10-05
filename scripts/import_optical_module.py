#!/usr/bin/env python3
"""Archive and verify the user-supplied OpticalModule bundle without executing it."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


DEFAULT_DEST = Path(__file__).resolve().parents[1] / 'local/vendor/optical_module_pu'
SKIP_DIRS = {'.git', '__pycache__', 'build', 'install', 'log', 'logs', 'logs_pc_flux',
             '.vscode', '.pytest_cache'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def import_bundle(source, destination):
    # Preflight the complete archive before creating any output.
    with zipfile.ZipFile(source) as archive:
        selected = []
        seen = set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                    or not path.parts or path.parts[0] != 'OpticalModule_PU'):
                raise ValueError(f'Unsafe archive member: {entry.filename}')
            if entry.is_dir():
                continue
            if any(p in SKIP_DIRS or p.endswith('.egg-info') for p in path.parts):
                continue
            if path.suffix == '.pyc':
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f'Symlink not supported: {entry.filename}')
            if str(path) in seen:
                raise ValueError(f'Duplicate archive member: {entry.filename}')
            seen.add(str(path))
            selected.append(entry)
        destination.mkdir(parents=True, exist_ok=False)
        archived = destination / 'OpticalModule_PU.zip'
        shutil.copyfile(source, archived)
        source_hash = digest(source)
        if digest(archived) != source_hash:
            raise ValueError('Archive copy checksum mismatch')
        records = []
        for entry in selected:
            target = destination / 'source' / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            # Preserve executable permissions for source scripts, without special bits.
            if (entry.external_attr >> 16) & 0o111:
                target.chmod(0o755)
            records.append({'path': str(target.relative_to(destination)),
                            'size': target.stat().st_size, 'sha256': digest(target)})
        manifest = {'schema_version': 1, 'source': str(source.resolve()),
                    'archive': archived.name, 'archive_sha256': source_hash,
                    'excluded_directory_names': sorted(SKIP_DIRS),
                    'note': 'Original ZIP complete; extracted source excludes generated files. No code executed.',
                    'files': records}
        (destination / 'provenance.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return manifest


def verify(destination):
    manifest = json.loads((destination / 'provenance.json').read_text())
    if digest(destination / manifest['archive']) != manifest['archive_sha256']:
        raise ValueError('Archive checksum mismatch')
    for record in manifest['files']:
        path = destination / record['path']
        if path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError(f'Checksum mismatch: {path}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import', 'verify'])
    parser.add_argument('source', nargs='?', type=Path)
    parser.add_argument('--destination', type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    if args.command == 'import' and args.source is None:
        parser.error('import requires a ZIP source')
    manifest = (import_bundle(args.source, args.destination)
                if args.command == 'import' else verify(args.destination))
    print(json.dumps({'destination': str(args.destination), 'files': len(manifest['files']),
                      'bytes': sum(f['size'] for f in manifest['files']),
                      'archive_sha256': manifest['archive_sha256']}, indent=2))


if __name__ == '__main__':
    main()
