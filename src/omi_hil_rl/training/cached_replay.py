"""Disk catalog + shared, byte-budgeted RAM working set for two replay streams.

The catalog is durable; evicting a resident transition never deletes experience.
During training the background loader opens samples; seed setup also validates
its source files. Sampling only copies prepared arrays.
The byte limit covers owned replay payloads, reserved loader workspace, batch
arrays and a metadata allowance, NOT total process RSS, CUDA or OS page cache.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import hashlib
from itertools import chain
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
import weakref

import numpy as np
import torch
from stable_baselines3.common.type_aliases import DictReplayBufferSamples

from .transition_replay import TransitionReplay, _spaces

VERSION = 'omi-cached-dual-replay-v1'
GIB = 1024**3
METADATA_ALLOWANCE = 8*1024**2


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()


class CachedDualReplay:
    is_dual = True
    is_cached = True

    def __init__(self, directory, contract, *, cache_bytes=16*GIB, memory_limit_bytes=20*GIB,
                 sources=(), refresh_every=200, recent_fraction=.5, turnover_fraction=.1,
                 prefetch=True, _reopen=False):
        self.directory = Path(directory).resolve()
        if not _reopen:
            self.directory.mkdir(parents=True, exist_ok=False)
        self.owner = (self.directory/'writer.lock').open('a+b')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise RuntimeError('cached replay already has a writer') from None
        self.db = None
        try:
            self.contract = json.loads(json.dumps(contract))
            self.observation_space, self.action_space = _spaces(contract)
            self.validator = TransitionReplay.__new__(TransitionReplay)
            self.validator.contract = self.contract
            self.validator.buffer = SimpleNamespace(observation_space=self.observation_space, action_space=self.action_space)
            self.payload_bytes = 2*sum(int(np.prod(s.shape))*s.dtype.itemsize
                                      for s in self.observation_space.spaces.values()) + int(np.prod(self.action_space.shape))*4 + 8
            # Includes a conservative allowance for each resident's Python/array headers.
            self.entry_bytes = self.payload_bytes+4096
            self.scratch_bytes = 8*self.entry_bytes+1024**2
            from omi_hil_rl.hil.observation_storage import ObservationReader
            self.reader = ObservationReader(cache_size=16)
            self.reader_bytes = 16*(self.payload_bytes//20+4096)
            if (type(cache_bytes) is not int or type(memory_limit_bytes) is not int or
                    cache_bytes < 3*self.entry_bytes or
                    memory_limit_bytes < cache_bytes+self.scratch_bytes+METADATA_ALLOWANCE+self.reader_bytes or
                    refresh_every < 1 or not 0 < recent_fraction < 1 or not 0 < turnover_fraction <= 1):
                raise ValueError('invalid cache budget: allow >=3 records plus loader and metadata headroom')
            self.cache_bytes, self.memory_limit_bytes = cache_bytes, memory_limit_bytes
            self.buffer_size = cache_bytes//self.entry_bytes
            self.buffer = self
            self.refresh_every, self.recent_fraction, self.turnover_fraction = refresh_every, recent_fraction, turnover_fraction
            for source in sources:
                if not Path(source).is_dir():
                    raise FileNotFoundError('recorded source directory missing: '+str(source))
            self.sources = [self._path(p) for p in sources]
            self.cv = threading.Condition(threading.RLock())
            self.io_lock = threading.RLock()
            self.cache = {}
            self.demo, self.online, self.seeds = set(), set(), set()
            self.work_bytes = self.batch_bytes = self.peak_bytes = 0
            self.samples = self.loads = self.evictions = self.refreshes = 0
            self.sample_seconds = 0.
            self.error = None
            self.closed = self.closing = self.busy = False
            self.seed_sealed = False
            self.pending, self.queued = deque(), set()
            self.imported_since_poll = 0
            self.next_scan = 0.
            self.refresh_requested = False
            self.prefetch = prefetch
            self.futures = {}
            self.prefetcher = ThreadPoolExecutor(max_workers=1, thread_name_prefix='omi-batch') if prefetch else None
            self.db = sqlite3.connect(self.directory/'catalog.sqlite3', check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA cache_size=-2048')
            self.db.execute('PRAGMA temp_store=FILE')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(
                    key TEXT PRIMARY KEY, path TEXT NOT NULL, sha TEXT NOT NULL,
                    seed INTEGER NOT NULL, count INTEGER NOT NULL, summary TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, step INTEGER NOT NULL,
                    stamp INTEGER NOT NULL, seed INTEGER NOT NULL, human INTEGER NOT NULL,
                    path TEXT NOT NULL, next_path TEXT, sha TEXT NOT NULL, next_sha TEXT,
                    origin TEXT NOT NULL, metadata TEXT NOT NULL,
                    UNIQUE(source,step));
                CREATE INDEX IF NOT EXISTS records_seed ON records(seed,stamp);
                CREATE INDEX IF NOT EXISTS records_human ON records(human,seed,stamp);
                CREATE INDEX IF NOT EXISTS sources_path ON sources(path);
            ''')
            saved = self.db.execute("SELECT value FROM settings WHERE key='seed_sealed'").fetchone()
            self.seed_sealed = bool(json.loads(saved[0])) if saved else False
            self.worker = threading.Thread(target=self._worker, name='omi-replay-loader', daemon=True)
            self.checkpoint()
            self.worker.start()
            self.refresh()
        except BaseException:
            if self.db is not None:
                self.db.close()
            if hasattr(self, 'prefetcher') and self.prefetcher:
                self.prefetcher.shutdown(wait=True, cancel_futures=True)
            self.owner.close()
            raise

    def _path(self, path):
        path = Path(path).resolve()
        return os.path.relpath(path, self.directory) if path.is_relative_to(self.directory.parent) else str(path)

    def _resolve(self, path):
        return (self.directory/path).resolve()

    @classmethod
    def reopen(cls, directory, *, expected_contract=None, prefetch=True, **unused):
        directory = Path(directory)
        m = json.loads((directory/'manifest.json').read_text())
        if m.get('backend') != VERSION or (expected_contract is not None and m['contract'] != expected_contract):
            raise ValueError('cached replay contract/backend mismatch')
        return cls(directory, m['contract'], cache_bytes=m['cache_bytes'], memory_limit_bytes=m['memory_limit_bytes'],
                   sources=[directory/p for p in m['sources']], refresh_every=m['refresh_every'],
                   recent_fraction=m['recent_fraction'], turnover_fraction=m['turnover_fraction'],
                   prefetch=prefetch, _reopen=True)

    def _ensure(self):
        if self.error:
            raise RuntimeError('replay background load failed: '+repr(self.error)) from self.error
        if self.closed or self.closing:
            raise RuntimeError('cached replay closed')

    def _used(self):
        return METADATA_ALLOWANCE+self.reader_bytes+len(self.cache)*self.entry_bytes+self.work_bytes+self.batch_bytes

    def _peak(self):
        self.peak_bytes = max(self.peak_bytes, self._used())
        if self._used() > self.memory_limit_bytes:
            raise AssertionError('replay byte accounting exceeded limit')

    def _evict(self, ident):
        self.demo.discard(ident)
        self.online.discard(ident)
        del self.cache[ident]
        self.evictions += 1

    def _room(self, amount):
        # Budget pressure is not permission to discard the other pool's
        # retained references. Only rolling selection retires cache entries.
        if self._used()+amount > self.memory_limit_bytes:
            raise MemoryError('replay memory limit: release held batches or reduce batch/cache size')

    @contextmanager
    def _workspace(self):
        with self.io_lock:
            with self.cv:
                self._ensure()
                self._room(self.scratch_bytes)
                self.work_bytes += self.scratch_bytes
                self._peak()
            try:
                yield
            finally:
                with self.cv:
                    self.work_bytes -= self.scratch_bytes
                    self.cv.notify_all()

    def validate(self, record, *, origin='online'):
        return self.validator.validate(record, origin=origin)

    def register_episode(self, manifest_path, *, seed=False, expected_hashes=None):
        """Atomically index a complete episode. Used by the loader or seed setup.

        Nothing is written to the source. The durable catalog, not a file in a
        possibly shared source run, owns duplicate-import detection.
        """
        from omi_hil_rl.hil.exchange import read_episode
        from omi_hil_rl.hil.periodic_bc_label import validate_bc_label
        from .replay_sources import periodic_records
        path = Path(manifest_path).resolve()
        manifest = json.loads(path.read_text())
        periodic = path.name == 'audit.json'
        if seed and periodic:
            raise ValueError('initial seed requires reviewed ready segments')
        key = ('seed:' if seed else 'online:')+manifest.get('episode', path.parent.name)
        fingerprint = digest(path)
        with self.cv:
            self._ensure()
            old = self.db.execute('SELECT * FROM sources WHERE key=?', (key,)).fetchone()
            if old:
                if old['sha'] != fingerprint or self._resolve(old['path']) != path:
                    raise ValueError('episode already indexed from different or changed source')
                return 0
            same_path = self.db.execute('SELECT seed FROM sources WHERE path=?', (self._path(path),)).fetchone()
            if same_path is not None and bool(same_path['seed']) != seed:
                raise ValueError('initial demonstration cannot also be registered as online experience')
            if seed and self.seed_sealed:
                raise ValueError('initial demonstrations are sealed')
        summary = {}
        if periodic:
            origin = 'online'
            iterator = periodic_records(path.parent, self.contract, self.validator, summary, reader=self.reader)
        else:
            if manifest['contract'] != self.contract or not manifest['keep'] or manifest['count'] < 1:
                raise ValueError('unready or mismatched source episode')
            if not seed and manifest['origin'] != 'online':
                raise ValueError('runtime records require online origin')
            origin = manifest['origin']
            iterator = ((path.parent/f"{r['step']:06d}.npz", None, r) for r in
                        read_episode(path.parent, manifest, reader=self.reader))
        # Stage small index rows in a TEMP on-disk table. No whole-episode arrays
        # and no unbounded Python list are kept while checking data.
        with self._workspace():
            count = 0
            with self.cv:
                self.db.execute('CREATE TEMP TABLE IF NOT EXISTS staged AS SELECT * FROM records WHERE 0')
                self.db.execute('DELETE FROM staged')
            for current_path, next_path, record in iterator:
                if self.closing:
                    raise RuntimeError('replay closed during registration')
                self.validate(record, origin=origin)
                if seed:
                    validate_bc_label(self.contract, record['executed_action'], record)
                    if record['action_source'] != 'human':
                        raise ValueError('seed may contain only human actions')
                current_sha = digest(current_path)
                if expected_hashes is not None and current_sha != expected_hashes[count]:
                    raise ValueError('seed sample hash changed')
                meta = {k: v for k, v in record.items() if k not in ('observation', 'next_observation', 'executed_action')}
                meta['executed_action'] = np.asarray(record['executed_action']).tolist()
                row = (key, record['step'], record['observation_time_ns'], int(seed),
                       int(record['action_source']=='human'), self._path(current_path),
                       self._path(next_path) if next_path is not None else None, current_sha,
                       digest(next_path) if next_path is not None else None, origin, json.dumps(meta, allow_nan=False))
                with self.cv:
                    self.db.execute('INSERT INTO staged VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)', row)
                count += 1
            if expected_hashes is not None and count != len(expected_hashes):
                raise ValueError('seed hash count mismatch')
            if digest(path) != fingerprint:
                raise ValueError('source changed while being indexed')
            with self.cv:
                if seed:
                    n = self.db.execute('SELECT COUNT(*) FROM records WHERE seed=1').fetchone()[0]+count
                    if n+2 > self.buffer_size:
                        raise ValueError('cache cannot hold protected seed plus online/human working slots')
                self.db.execute('INSERT INTO records SELECT * FROM staged')
                self.db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?)',
                    (key, self._path(path), fingerprint, int(seed), count, json.dumps(summary)))
                self.db.execute('DELETE FROM staged')
                self.db.commit()
                self.imported_since_poll += 0 if seed else count
        self.refresh()
        return count

    def seal_seed(self):
        with self.cv:
            self._ensure()
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('seed_sealed','true')")
            self.db.commit()
            self.seed_sealed = True
        self.checkpoint()
        self.refresh()

    def add_sources(self, sources):
        with self.cv:
            for path in sources:
                if not Path(path).is_dir():
                    raise FileNotFoundError('recorded source directory missing: '+str(path))
                relative = self._path(path)
                if relative not in self.sources:
                    self.sources.append(relative)
            self.next_scan = 0.
        self.checkpoint()

    def import_ready(self, run):
        """Nonblocking discovery. Raw audit takes precedence over its segments."""
        with self.cv:
            self._ensure()
            result, self.imported_since_poll = self.imported_since_poll, 0
            if time.monotonic() < self.next_scan:
                return result
            self.next_scan = time.monotonic()+1.
        for root in dict.fromkeys([Path(run).resolve(), *[self._resolve(p) for p in self.sources]]):
            paths = chain(root.glob('periodic_episodes/*/audit.json'),
                (p for p in root.glob('episodes/*/ready.json') if not
                 (root/'periodic_episodes'/p.parent.name.rsplit('-segment-', 1)[0]/'staging.json').exists()))
            for path in paths:
                with self.cv:
                    if len(self.pending) >= 32:
                        break
                    registered = self.db.execute('SELECT * FROM sources WHERE path=?', (self._path(path),)).fetchone()
                    if registered:
                        if digest(path) != registered['sha']:
                            raise ValueError('registered episode manifest changed: '+str(path))
                        self._registration_receipts(path, registered['key'])
                        continue
                    if str(path) not in self.queued:
                        self.pending.append(path)
                        self.queued.add(str(path))
                        self.cv.notify_all()
        return result

    def _registration_receipts(self, path, key):
        """Compatibility markers only in this replay's owning run, never an external source."""
        from omi_hil_rl.hil.exchange import atomic_json
        run = self.directory.parent
        if path.parent.parent == run/'episodes':
            paths = [path]
        elif path.parent.parent == run/'periodic_episodes':
            paths = list((run/'episodes').glob(path.parent.name+'-segment-*/ready.json'))
        else:
            return
        for ready in paths:
            marker = ready.parent/'imported.json'
            if marker.exists():
                continue
            m = json.loads(ready.read_text())
            start = int(ready.parent.name.rsplit('-segment-', 1)[1]) if path.name=='audit.json' else 0
            n = self.db.execute('SELECT COUNT(*) FROM records WHERE source=? AND step>=? AND step<?',
                                (key, start, start+m['count'])).fetchone()[0]
            if n == m['count']:
                atomic_json(marker, dict(backend=VERSION, count=n, episode=m['episode'],
                    catalog_registered=True, resident_not_guaranteed=True))

    def _select(self, where, quota, previous):
        """Recent anchors plus a slowly refreshed random historical subset."""
        if quota <= 0:
            return set()
        recent_n = max(1, math.ceil(quota*self.recent_fraction))
        recent = {r[0] for r in self.db.execute(
            f'SELECT id FROM records WHERE {where} ORDER BY stamp DESC,id DESC LIMIT ?', (recent_n,))}
        remaining = quota-len(recent)
        old = list(previous-recent)
        np.random.shuffle(old)
        keep = set(old[:max(0, remaining-max(1, math.ceil(remaining*self.turnover_fraction)))])
        chosen = recent | keep
        # Bounded rows returned to Python. SQLite performs any large scan on disk.
        for row in self.db.execute(f'SELECT id FROM records WHERE {where} ORDER BY RANDOM() LIMIT ?', (quota*2,)):
            if len(chosen) >= quota:
                break
            chosen.add(row[0])
        return chosen

    def _load(self, row):
        path = self._resolve(row['path'])
        if digest(path) != row['sha']:
            raise ValueError('registered transition file changed: '+str(path))
        reader = self.reader
        record = json.loads(row['metadata'])
        record['observation'] = reader.read(path)[1]
        if row['next_path']:
            nxt = self._resolve(row['next_path'])
            if digest(nxt) != row['next_sha']:
                raise ValueError('registered next observation changed: '+str(nxt))
            record['next_observation'] = reader.read(nxt)[1]
        else:
            record['next_observation'] = reader.read(path, 'next_observation')[1]
        values, action, _, reward, terminated, truncated, source = self.validate(record, origin=row['origin'])
        return ({k: v[0] for k, v in values[0].items()}, {k: v[0] for k, v in values[1].items()},
                action, reward, float(terminated), bool(row['seed']), source=='human')

    def _refresh(self):
        with self.cv:
            nseed = self.db.execute('SELECT COUNT(*) FROM records WHERE seed=1').fetchone()[0]
            self.seeds = {r[0] for r in self.db.execute('SELECT id FROM records WHERE seed=1')}
            slots = self.buffer_size
            demo_quota = min(slots-1, max(nseed+max(1, (slots-nseed)//4), slots//2))
            demo = self.seeds | self._select('seed=0 AND human=1', demo_quota-nseed, self.demo-self.seeds)
            online = self._select('seed=0', slots-len(demo), self.online)
            # Reuse shared interventions to fill otherwise unused capacity.
            spare = slots-len(demo | online)
            if spare:
                for row in self.db.execute('SELECT id FROM records WHERE seed=0 ORDER BY stamp DESC,id DESC LIMIT ?', (slots,)):
                    if not spare:
                        break
                    if row[0] not in demo | online:
                        online.add(row[0]); spare -= 1
            wanted = demo | online
            # Keep old sampling references until replacements are available.
            # Add already-resident new selections without reclassifying every
            # resident human record into both pools.
            self.demo.update(demo & self.cache.keys())
            self.online.update(online & self.cache.keys())
            rows = [self.db.execute('SELECT id,seed,human,source,step FROM records WHERE id=?', (i,)).fetchone()
                    for i in wanted-self.cache.keys()]
            rows.sort(key=lambda r: (not r['seed'], not r['human'], r['source'], r['step']))
        for row in rows:
            if self.closing:
                return
            with self._workspace():
                with self.cv:
                    row = self.db.execute('SELECT * FROM records WHERE id=?', (row['id'],)).fetchone()
                values = self._load(row)
                with self.cv:
                    if len(self.cache) >= slots:
                        victim = next((i for i in self.cache if i not in wanted and i not in self.seeds
                            and (i not in self.demo or len(self.demo)>1 or row['id'] in demo)
                            and (i not in self.online or len(self.online)>1 or row['id'] in online)), None)
                        if victim is None:
                            raise RuntimeError('no replaceable cache slot')
                        self._evict(victim)
                    # Workspace reservation already covers the newly decoded
                    # record; convert part of that reservation to residency.
                    self._room(self.entry_bytes)
                    self.cache[row['id']] = values
                    if row['id'] in demo:
                        self.demo.add(row['id'])
                    if row['id'] in online:
                        self.online.add(row['id'])
                    self.loads += 1
                    self._peak()
                    self.cv.notify_all()
        with self.cv:
            if wanted <= self.cache.keys():
                # Atomically publish each pool's own selections. A record can
                # now belong to Demo only or RL only regardless of its origin.
                self.demo = demo
                self.online = online
                for ident in list(self.cache):
                    if ident not in wanted:
                        self._evict(ident)
            self.refreshes += 1

    def _worker(self):
        try:
            while True:
                with self.cv:
                    self.cv.wait_for(lambda: self.closing or self.pending or self.refresh_requested)
                    if self.closing:
                        return
                    path = self.pending.popleft() if self.pending else None
                    self.refresh_requested = False
                    self.busy = True
                if path is not None:
                    self.register_episode(path)
                    with self.cv:
                        registered = self.db.execute('SELECT key FROM sources WHERE path=?', (self._path(path),)).fetchone()
                        self._registration_receipts(path, registered['key'])
                with self.cv:
                    self.refresh_requested = False
                self._refresh()
                with self.cv:
                    self.busy = False
                    if path is not None:
                        self.queued.discard(str(path))
                    self.cv.notify_all()
        except BaseException as exc:
            with self.cv:
                if not self.closing:
                    self.error = exc
                self.busy = False
                self.cv.notify_all()

    def refresh(self):
        with self.cv:
            self.refresh_requested = True
            self.cv.notify_all()

    def wait_idle(self, timeout=120.):
        with self.cv:
            if not self.cv.wait_for(lambda: self.error or (not self.busy and not self.pending and not self.refresh_requested), timeout):
                raise TimeoutError('replay loader still busy')
            self._ensure()

    def stream_counts(self):
        with self.cv:
            self._ensure()
            fixed = len(self.seeds & self.cache.keys())
            return dict(online=len(self.online), demonstration=len(self.demo), initial_demonstration=fixed,
                        intervention=len(self.demo-self.seeds), offline_demonstration=fixed)

    def size(self):
        with self.cv:
            self._ensure()
            return len(self.cache)

    def storage_stats(self):
        with self.cv:
            rows = self.db.execute('SELECT seed,human,COUNT(*) AS n FROM records GROUP BY seed,human').fetchall()
            counts = {(r['seed'], r['human']): r['n'] for r in rows}
            return dict(backend=VERSION, cache_target_bytes=self.cache_bytes, memory_limit_bytes=self.memory_limit_bytes,
                resident_bytes=len(self.cache)*self.entry_bytes, resident_unique=len(self.cache),
                batch_bytes=self.batch_bytes, loader_reserved_bytes=self.work_bytes,
                managed_bytes=self._used(), peak_managed_bytes=self.peak_bytes,
                metadata_allowance_bytes=METADATA_ALLOWANCE, loads=self.loads, evictions=self.evictions,
                frame_cache_reserved_bytes=self.reader_bytes,
                refreshes=self.refreshes, samples=self.samples, sample_seconds=self.sample_seconds,
                catalog_seed=counts.get((1, 1), 0), catalog_online=counts.get((0, 0), 0)+counts.get((0, 1), 0),
                catalog_interventions=counts.get((0, 1), 0), pending_episodes=len(self.pending),
                loader_busy=self.busy, loader_error=repr(self.error) if self.error else None)

    def _batch(self, batch_size, human):
        start = time.monotonic()
        if batch_size < 1 or (not human and (batch_size < 2 or batch_size % 2)):
            raise ValueError('dual replay requires even batch size >=2; human batch >=1')
        with self.cv:
            self._ensure()
            if not self.demo or (not human and not self.online):
                raise RuntimeError('required resident demo/online stream is empty; wait for loader')
            nbytes = batch_size*self.payload_bytes
            # Do not evict selected data while assembling it. Budget failure is
            # explicit and happens before allocating any batch arrays.
            loader_headroom = max(0, self.scratch_bytes-self.work_bytes)
            if self._used()+nbytes+loader_headroom > self.memory_limit_bytes:
                raise MemoryError('batch exceeds replay memory limit; reduce batch/cache or release held batches')
            ids = list(np.random.choice(list(self.demo), batch_size if human else batch_size//2))
            if not human:
                ids += list(np.random.choice(list(self.online), batch_size//2))
                np.random.shuffle(ids)
            self.batch_bytes += nbytes
            self._peak()
            arrays = []
            assigned = 0
            owner = weakref.ref(self)
            def release(size):
                buffer = owner()
                if buffer is not None:
                    with buffer.cv:
                        buffer.batch_bytes -= size
                        buffer.cv.notify_all()
            def allocate(shape, dtype):
                nonlocal assigned
                a = np.empty(shape, dtype=dtype)
                assigned += a.nbytes
                weakref.finalize(a, release, a.nbytes)
                arrays.append(a)
                return a
            try:
                obs = {k: allocate((batch_size, *s.shape), s.dtype) for k, s in self.observation_space.spaces.items()}
                nxt = {k: allocate((batch_size, *s.shape), s.dtype) for k, s in self.observation_space.spaces.items()}
                actions = allocate((batch_size, *self.action_space.shape), np.float32)
                rewards, dones = allocate((batch_size, 1), np.float32), allocate((batch_size, 1), np.float32)
                for i, ident in enumerate(ids):
                    record = self.cache[ident]
                    for k in obs:
                        obs[k][i], nxt[k][i] = record[0][k], record[1][k]
                    actions[i], rewards[i, 0], dones[i, 0] = record[2:5]
                result = DictReplayBufferSamples(
                    observations={k: torch.from_numpy(v) for k, v in obs.items()},
                    next_observations={k: torch.from_numpy(v) for k, v in nxt.items()},
                    actions=torch.from_numpy(actions), rewards=torch.from_numpy(rewards), dones=torch.from_numpy(dones))
                self.samples += 1
                self.sample_seconds += time.monotonic()-start
                if self.samples % self.refresh_every == 0:
                    self.refresh()
                return result
            finally:
                # Account for any allocations which failed before finalizers
                # were installed. Existing arrays live as long as their tensors.
                self.batch_bytes -= nbytes-assigned

    def _sample(self, batch_size, human, env):
        if env is not None:
            raise ValueError('cached replay expects model-side normalization')
        self._ensure()
        if not self.prefetch:
            return self._batch(batch_size, human)
        previous = self.futures.pop(human, None)
        if previous is None:
            result = self._batch(batch_size, human)
        else:
            n, future = previous
            result = future.result()
            if n != batch_size:
                del result
                result = self._batch(batch_size, human)
        self.futures[human] = (batch_size, self.prefetcher.submit(self._batch, batch_size, human))
        return result

    def sample(self, batch_size, env=None):
        return self._sample(batch_size, False, env)

    def sample_human(self, batch_size, env=None):
        return self._sample(batch_size, True, env)

    def checkpoint(self):
        from omi_hil_rl.hil.exchange import atomic_json
        with self.cv:
            # Registration commits only whole validated episodes. Cache arrays
            # need no checkpoint and are rebuilt after restart.
            self.db.commit()
            self.db.execute('PRAGMA wal_checkpoint(FULL)')
            atomic_json(self.directory/'manifest.json', dict(backend=VERSION, clean=True, contract=self.contract,
                cache_bytes=self.cache_bytes, memory_limit_bytes=self.memory_limit_bytes, capacity=self.buffer_size,
                sources=self.sources, refresh_every=self.refresh_every, recent_fraction=self.recent_fraction,
                turnover_fraction=self.turnover_fraction))

    def close(self):
        if self.closed:
            return
        with self.cv:
            self.closing = True
            self.cv.notify_all()
        self.worker.join()
        if self.prefetcher:
            self.prefetcher.shutdown(wait=True, cancel_futures=True)
        self.futures.clear()
        with self.cv:
            self.cache.clear(); self.demo.clear(); self.online.clear()
            self.reader.cache.clear()
            self.db.rollback()
            self.checkpoint()
            self.db.close()
            self.owner.close()
            self.closed = True
