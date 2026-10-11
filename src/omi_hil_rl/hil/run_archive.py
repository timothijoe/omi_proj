"""Portable, verified stopped-run archives; no ROS or robot output.

pack/verify/restore use only the Python standard library. probe-buffer lazily
loads the project replay code and rebuilds a disposable cache on a local disk.
"""
import argparse
from contextlib import contextmanager, ExitStack, closing
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

VERSION = 'omi-training-archive-v1'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4*1024**2), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


class HashReader:
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data)
        return data


class HashWriter:
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()

    def write(self, data):
        self.hash.update(data)
        return self.stream.write(data)


@contextmanager
def stopped_run(run):
    """Never create locks in an archive: only lock an existing stopped run."""
    with ExitStack() as stack:
        for name in ('actor.lock', 'learner.lock', 'replay/writer.lock'):
            path = run/name
            if path.exists():
                stream = stack.enter_context(path.open('rb'))
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('run is in use: '+str(path)) from None
        for name in ('async_state.json', 'monitor/actor.json', 'monitor/learner.json'):
            path = run/name
            if path.exists():
                state = json.loads(path.read_text())
                if state.get('phase') != 'CLOSED' or state.get('error') or state.get('learner_forced_kill'):
                    raise ValueError('run must be cleanly CLOSED before archival/probing: '+name)
        manifest = json.loads((run/'replay/manifest.json').read_text())
        if manifest.get('backend') != 'omi-cached-dual-replay-v1' or not manifest.get('clean'):
            raise ValueError('a clean cached replay is required')
        wal = run/'replay/catalog.sqlite3-wal'
        if wal.exists() and wal.stat().st_size:
            raise ValueError('nonempty SQLite WAL: close/checkpoint replay before archiving')
        yield manifest


def readonly_db(path):
    # Only used after stopped_run rejects nonempty WAL; avoids creating SHM/WAL.
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1', uri=True)


def portable_catalog(run, manifest):
    if manifest.get('sources') or json.loads((run/'dataset.json').read_text()).get('episodes'):
        raise ValueError('external/seed datasets are not bundled by this interface; use a self-contained weights-only run')
    with closing(readonly_db(run/'replay/catalog.sqlite3')) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        for query in ('SELECT path FROM sources', 'SELECT path FROM records',
                      'SELECT next_path FROM records WHERE next_path IS NOT NULL'):
            for (name,) in db.execute(query):
                if Path(name).is_absolute() or not (run/'replay'/name).resolve().is_relative_to(run):
                    raise ValueError('catalog has nonportable source pointer: '+name)
                if not (run/'replay'/name).is_file():
                    raise ValueError('catalog source missing: '+name)
        return [dict(seed=bool(s), human=bool(h), count=n) for s,h,n in
                db.execute('SELECT seed,human,COUNT(*) FROM records GROUP BY seed,human')]


def make_tar(root, files, archive, inventory, prefix):
    count, total, last = 0, 0, time.monotonic()
    with archive.open('wb', buffering=8*1024**2) as raw, inventory.open('w') as index:
        writer = HashWriter(raw)
        with tarfile.open(fileobj=writer, mode='w|', format=tarfile.PAX_FORMAT) as tar:
            for relative in files:
                path = root/relative
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('symlink/external file must be resolved explicitly: '+str(path))
                before = path.stat()
                info = tar.gettarinfo(str(path), arcname=prefix+'/'+relative)
                if not info.isfile():
                    raise ValueError('only regular files can be archived: '+relative)
                info.uid = info.gid = 0; info.uname = info.gname = ''
                with path.open('rb') as stream:
                    reader = HashReader(stream)
                    tar.addfile(info, reader)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError('source changed while archiving: '+relative)
                index.write(json.dumps(dict(path=relative, size=info.size, sha256=reader.hash.hexdigest()))+'\n')
                count += 1; total += info.size
                if time.monotonic()-last > 10:
                    print(json.dumps(dict(stage='packing', archive=archive.name, files=count, bytes=total)), flush=True)
                    last = time.monotonic()
        raw.flush(); os.fsync(raw.fileno())
        index.flush(); os.fsync(index.fileno())
    return dict(archive=archive.name, inventory=inventory.name, prefix=prefix,
                sha256=writer.hash.hexdigest(), inventory_sha256=digest(inventory), files=count, bytes=total)


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or str(p) != name or '\\' in name:
        raise ValueError('unsafe archive path: '+name)
    return p


def check_tar(bundle, spec, destination=None):
    archive, inventory = bundle/spec['archive'], bundle/spec['inventory']
    if digest(inventory) != spec['inventory_sha256']:
        raise ValueError('inventory checksum mismatch')
    entries = {}
    for line in inventory.read_text().splitlines():
        row = json.loads(line); safe_relative(row['path'])
        if row['path'] in entries:
            raise ValueError('duplicate inventory entry')
        entries[row['path']] = row
    seen, total, last = set(), 0, time.monotonic()
    with archive.open('rb', buffering=8*1024**2) as raw:
        reader = HashReader(raw)
        with tarfile.open(fileobj=reader, mode='r|') as tar:
            for member in tar:
                safe_relative(member.name)
                prefix = spec['prefix']+'/'
                if not member.name.startswith(prefix) or not member.isfile() or member.issparse():
                    raise ValueError('unexpected archive member: '+member.name)
                relative = member.name[len(prefix):]
                safe_relative(relative)
                row = entries.get(relative)
                if row is None or relative in seen or row['size'] != member.size:
                    raise ValueError('unexpected/duplicate/incorrect size: '+relative)
                h = hashlib.sha256()
                with ExitStack() as stack:
                    src = stack.enter_context(tar.extractfile(member))
                    dst = None
                    if destination is not None:
                        path = destination/relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        dst = stack.enter_context(path.open('xb'))
                    for block in iter(lambda: src.read(4*1024**2), b''):
                        h.update(block)
                        if dst is not None: dst.write(block)
                if h.hexdigest() != row['sha256']:
                    raise ValueError('file checksum mismatch: '+relative)
                if destination is not None:
                    os.chmod(path, member.mode & 0o777)
                    os.utime(path, (member.mtime, member.mtime))
                seen.add(relative); total += row['size']
                if time.monotonic()-last > 10:
                    print(json.dumps(dict(stage='restoring' if destination else 'verifying',
                        archive=archive.name, files=len(seen), bytes=total)), flush=True)
                    last = time.monotonic()
        while reader.read(4*1024**2): pass  # include tar padding in whole-archive hash
    if seen != entries.keys() or len(seen) != spec['files'] or total != spec['bytes']:
        raise ValueError('archive inventory/count mismatch')
    if reader.hash.hexdigest() != spec['sha256']:
        raise ValueError('whole archive checksum mismatch')
    return dict(files=len(seen), bytes=total)


def load_manifest(bundle, *, allow_incomplete=False):
    if not allow_incomplete and (bundle/'ARCHIVE_INCOMPLETE').exists():
        raise ValueError('archive was not completed; do not restore')
    m = json.loads((bundle/'manifest.json').read_text())
    if m.get('schema') != VERSION:
        raise ValueError('unsupported archive format')
    for spec in m['payloads'].values():
        for key in ('archive', 'inventory', 'prefix'): safe_relative(spec[key])
    return m


def verify(bundle, *, allow_incomplete=False):
    bundle = Path(bundle).resolve(); m = load_manifest(bundle, allow_incomplete=allow_incomplete)
    for name, sha in m['sidecars'].items():
        safe_relative(name)
        if digest(bundle/name) != sha: raise ValueError('sidecar checksum mismatch: '+name)
    return {key: check_tar(bundle, spec) for key,spec in m['payloads'].items()}


def pack(run, output, *, code_root=None, initial_bc=None, tutorial=None):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.is_relative_to(run) or (output.exists() and any(output.iterdir())):
        raise ValueError('archive output must be empty and outside the run')
    with stopped_run(run) as replay_manifest:
        counts = portable_catalog(run, replay_manifest)
        paths = list(run.rglob('*'))
        if any(p.is_symlink() for p in paths):
            raise ValueError('run contains symlinks; package dependencies explicitly first')
        files = sorted(str(p.relative_to(run)) for p in paths if p.is_file()
                       and p.name not in ('catalog.sqlite3-wal', 'catalog.sqlite3-shm'))
        source_bytes = sum((run/f).stat().st_size for f in files)
        output.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(output).free < source_bytes*1.15+1024**3:
            raise ValueError('insufficient archive disk space')
        (output/'ARCHIVE_INCOMPLETE').write_text('Incomplete until verification finishes.\n')
        m = dict(schema=VERSION, created_utc=datetime.now(timezone.utc).isoformat(),
                 source_run=str(run), run_name=run.name, catalog=counts, payloads={}, sidecars={})
        print(json.dumps(dict(stage='start', files=len(files), bytes=source_bytes, output=str(output))), flush=True)
        m['payloads']['run'] = make_tar(run, files, output/'run.tar', output/'run_files.sha256.jsonl', 'run')
        sidecars = {'checkpoints/actor.pt':run/'actor.pt', 'checkpoints/learner.pt':run/'learner.pt',
                    'archive_tool.py':Path(__file__).resolve()}
        if initial_bc:
            for name in ('actor.pt', 'config.json', 'recipe.json'):
                source = Path(initial_bc)/name
                if not source.is_file(): raise ValueError('initial BC artifact missing: '+str(source))
                sidecars['initial_bc/'+name] = source
        if tutorial: sidecars['README.md'] = Path(tutorial)
        for name,source in sidecars.items():
            target = output/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if digest(source) != digest(target): raise ValueError('sidecar copy mismatch')
            m['sidecars'][name] = digest(target)
        if code_root:
            code_root = Path(code_root).resolve()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(code_root), *args])
            code_files = sorted(set(p.decode() for p in git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
                                    if p and (code_root/p.decode()).is_file()
                                    and not (code_root/p.decode()).resolve().is_relative_to(output)))
            m['code'] = dict(head=git('rev-parse', 'HEAD').decode().strip(),
                            branch=git('branch', '--show-current').decode().strip(),
                            status=git('status', '--short').decode())
            m['payloads']['code'] = make_tar(code_root, code_files, output/'source.tar',
                                            output/'source_files.sha256.jsonl', 'source')
        packages = {}
        for name in ('torch', 'numpy', 'stable-baselines3', 'gymnasium', 'Pillow', 'PyYAML'):
            try: packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: packages[name] = None
        write_json(output/'environment.json', dict(python=sys.version, platform=platform.platform(), packages=packages,
            note='Environment/SDKs are not bundled; source snapshot and checkpoints are included.'))
        m['sidecars']['environment.json'] = digest(output/'environment.json')
        write_json(output/'manifest.json', m)
        for path in output.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream: os.fsync(stream.fileno())
        results = verify(output, allow_incomplete=True)
        (output/'ARCHIVE_INCOMPLETE').unlink()
        return dict(status='verified', archive=str(output), source_retained=True, verified=results)


def restore(bundle, destination, *, payload='run'):
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    m = load_manifest(bundle)
    if destination.exists() or destination.is_relative_to(bundle):
        raise ValueError('restore into a NEW local directory outside the archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fstype = subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(destination.parent)], text=True).strip()
    if fstype in ('exfat', 'vfat', 'ntfs', 'ntfs3', 'fuseblk'):
        raise ValueError('restore working replay to a local POSIX filesystem (e.g. ext4), not '+fstype)
    spec = m['payloads'][payload]
    if shutil.disk_usage(destination.parent).free < spec['bytes']*1.1+128*1024**2:
        raise ValueError('insufficient restore space')
    tmp = Path(tempfile.mkdtemp(prefix='.'+destination.name+'.restore-', dir=destination.parent))
    try:
        result = check_tar(bundle, spec, tmp)
        if destination.exists(): raise ValueError('restore destination appeared during extraction')
        tmp.rename(destination)
    except BaseException:
        shutil.rmtree(tmp)
        raise
    return dict(status='restored', destination=str(destination), payload=payload, **result)


def probe_buffer(run, *, cache_gib=1., limit_gib=2., batch_size=64, timeout=1200.):
    import numpy as np
    import torch
    from omi_hil_rl.training.cached_replay import CachedDualReplay
    run = Path(run).resolve()
    if batch_size < 2 or batch_size % 2: raise ValueError('even batch size >=2 required')
    with stopped_run(run) as m, tempfile.TemporaryDirectory(prefix='omi-replay-probe-') as temp:
        portable_catalog(run, m)
        before = {n:digest(run/n) for n in ('actor.pt','learner.pt','replay/catalog.sqlite3','replay/manifest.json')}
        actor = torch.load(run/'actor.pt', map_location='cpu', weights_only=True)
        learner = torch.load(run/'learner.pt', map_location='cpu', weights_only=True)
        if actor['contract'] != m['contract'] or learner['contract'] != m['contract'] or actor['updates'] != learner['updates']:
            raise ValueError('restored model/contract/update mismatch')
        version = learner['updates']; del actor, learner
        scratch = Path(temp)/'replay'; scratch.mkdir()
        shutil.copyfile(run/'replay/catalog.sqlite3', scratch/'catalog.sqlite3')
        # Rebase ONLY the disposable catalog. Immutable original data stays read-only.
        with closing(sqlite3.connect(scratch/'catalog.sqlite3')) as db:
            for table, columns in (('sources', ('path',)), ('records', ('path','next_path'))):
                for column in columns:
                    rows = db.execute(f'SELECT rowid,{column} FROM {table} WHERE {column} IS NOT NULL').fetchall()
                    db.executemany(f'UPDATE {table} SET {column}=? WHERE rowid=?',
                        [(str((run/'replay'/name).resolve()), ident) for ident,name in rows])
            db.commit()
        replay = CachedDualReplay(scratch, m['contract'], cache_bytes=int(cache_gib*2**30),
                    memory_limit_bytes=int(limit_gib*2**30), prefetch=False, _reopen=True)
        try:
            replay.wait_idle(timeout)
            if not replay.demo or not replay.online:
                raise ValueError('need both new human Demo and online data to probe mixed sampling')
            mixed, human = replay.sample(batch_size), replay.sample_human(batch_size)
            for batch in (mixed, human):
                for obs in (batch.observations, batch.next_observations):
                    assert obs['rgb'].shape[1:]==(10,3,128,128)
                    assert np.isfinite(obs['tactile'].numpy()).all()
                assert torch.isfinite(batch.actions).all()
            result = dict(status='passed', checkpoint_version=version, robot_output=False, training_updates=0,
                streams=replay.stream_counts(), cache=replay.storage_stats(),
                batch_size=batch_size, rgb_shape=list(mixed.observations['rgb'].shape),
                tactile_shape=list(mixed.observations['tactile'].shape),
                note='RAM selection rebuilt, not a bitwise replay of the old sampling sequence')
            del mixed, human
        finally:
            replay.close()
        assert all(digest(run/n)==sha for n,sha in before.items())
        result['original_checkpoints_and_catalog_unchanged'] = True
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    c = commands.add_parser('pack'); c.add_argument('--run', required=True, type=Path)
    c.add_argument('--output', required=True, type=Path); c.add_argument('--code-root', type=Path)
    c.add_argument('--initial-bc', type=Path); c.add_argument('--tutorial', type=Path)
    c = commands.add_parser('verify'); c.add_argument('--archive', required=True, type=Path)
    for name,payload in (('restore','run'),('restore-code','code')):
        c = commands.add_parser(name); c.set_defaults(payload=payload)
        c.add_argument('--archive', required=True, type=Path); c.add_argument('--dest', required=True, type=Path)
    c = commands.add_parser('probe-buffer'); c.add_argument('--run', required=True, type=Path)
    c.add_argument('--cache-target-gib', type=float, default=1.); c.add_argument('--cache-limit-gib', type=float, default=2.)
    c.add_argument('--batch-size', type=int, default=64); c.add_argument('--timeout', type=float, default=1200.)
    c.add_argument('--report', type=Path)
    a = p.parse_args()
    if a.command=='pack': result=pack(a.run,a.output,code_root=a.code_root,initial_bc=a.initial_bc,tutorial=a.tutorial)
    elif a.command=='verify': result=verify(a.archive)
    elif a.command in ('restore','restore-code'): result=restore(a.archive,a.dest,payload=a.payload)
    else:
        result=probe_buffer(a.run,cache_gib=a.cache_target_gib,limit_gib=a.cache_limit_gib,batch_size=a.batch_size,timeout=a.timeout)
        if a.report:
            if a.report.exists(): raise ValueError('report already exists')
            a.report.parent.mkdir(parents=True,exist_ok=True);write_json(a.report,result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__=='__main__': main()
