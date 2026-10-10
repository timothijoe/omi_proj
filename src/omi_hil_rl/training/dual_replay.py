"""Two logical disk pools: sealed seed + rolling interventions, and online.

One owner, synchronous learner writes. A top-level dirty manifest guards
multi-store transactions; interrupted writes are refused, not silently repaired.
"""
import fcntl
import json
from pathlib import Path

import numpy as np

from .transition_replay import TransitionReplay

VERSION = 'omi-dual-replay-v1'
POOL_PATHS = dict(seed='demo/initial', interventions='demo/interventions', online='online')


def atomic(path, value):
    from omi_hil_rl.hil.exchange import atomic_json
    atomic_json(path, value)


class DualTransitionReplay:
    is_dual = True

    def __init__(self, directory, contract, *, seed_capacity, online_capacity, intervention_capacity):
        if min(seed_capacity, online_capacity, intervention_capacity) < 1:
            raise ValueError('positive replay capacities required')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self._lock_owner()
        self.contract = json.loads(json.dumps(contract))
        self.pools = {}
        self.seed_sealed, self.failed, self.closed = False, False, False
        self.dirty, self.last_import = True, None
        try:
            for name, capacity in [('seed', seed_capacity), ('online', online_capacity), ('interventions', intervention_capacity)]:
                self.pools[name] = TransitionReplay(self.directory/POOL_PATHS[name], contract, capacity, prefetch=False, demo_fraction=0.)
            self._facade()
            self.checkpoint()
        except BaseException:
            self._release()
            raise

    def _lock_owner(self):
        self.owner = (self.directory/'writer.lock').open('a+b')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.owner.close()
            raise RuntimeError('dual replay already has a writer') from None

    def _facade(self):
        self.buffer = self
        self.observation_space = self.pools['online'].buffer.observation_space
        self.action_space = self.pools['online'].buffer.action_space
        self.buffer_size = self.pools['online'].buffer.buffer_size

    @classmethod
    def reopen(cls, directory, *, expected_contract=None, **unused):
        self = cls.__new__(cls)
        self.directory = Path(directory)
        self._lock_owner()
        self.pools = {}
        self.closed, self.failed, self.dirty = False, False, False
        try:
            manifest = json.loads((self.directory/'manifest.json').read_text())
            if manifest.get('backend') != VERSION or not manifest.get('clean'):
                raise ValueError('dual replay has no clean checkpoint; restore a clean backup')
            self.contract = manifest['contract']
            if expected_contract is not None and self.contract != expected_contract:
                raise ValueError('dual replay contract mismatch')
            self.seed_sealed, self.last_import = manifest['seed_sealed'], manifest.get('last_import')
            for name in ('seed', 'online', 'interventions'):
                self.pools[name] = TransitionReplay.reopen(self.directory/POOL_PATHS[name], expected_contract=self.contract, prefetch=False)
            self._facade()
            return self
        except BaseException:
            self._release()
            raise

    def _manifest(self, clean):
        return dict(backend=VERSION, clean=clean, contract=self.contract, seed_sealed=self.seed_sealed,
                    last_import=self.last_import, capacity=self.buffer_size,
                    capacities={k: p.buffer.buffer_size for k, p in self.pools.items()})

    def _ensure(self):
        if self.closed or self.failed:
            raise RuntimeError('dual replay closed or partial write failed')

    def _mark_dirty(self):
        self._ensure()
        if not self.dirty:
            atomic(self.directory/'manifest.json', self._manifest(False))
            self.dirty = True

    def append_seed(self, record, *, origin='online'):
        self.validate(record, origin=origin)
        if self.seed_sealed or record['action_source'] != 'human':
            raise ValueError('initial seed must be unsealed human data')
        seed = self.pools['seed']
        if seed.buffer.size() >= seed.buffer.buffer_size:
            raise ValueError('initial seed is protected: capacity exceeded')
        self._mark_dirty()
        try:
            seed.append(record, origin=origin)
        except BaseException:
            self.failed = True
            raise

    def seal_seed(self):
        self._mark_dirty()
        self.seed_sealed = True
        self.checkpoint()

    def validate(self, record, *, origin='online'):
        return self.pools['online'].validate(record, origin=origin)

    def append(self, record, *, origin='online'):
        self.validate(record, origin=origin)
        if origin != 'online' or not self.seed_sealed:
            raise ValueError('seal initial seed first; runtime imports must be online')
        self._mark_dirty()
        try:
            slot = self.pools['online'].append(record, origin='online')
            if record['action_source'] == 'human':
                self.pools['interventions'].append(record, origin='online')
            return slot
        except BaseException:
            self.failed = True
            raise

    def size(self):
        self._ensure()
        return self.pools['seed'].buffer.size() + self.pools['online'].buffer.size()

    def stream_counts(self):
        self._ensure()
        fixed, online, intervention = (self.pools[k].buffer.size() for k in ('seed', 'online', 'interventions'))
        return dict(online=online, demonstration=fixed+intervention, initial_demonstration=fixed,
                    intervention=intervention, offline_demonstration=fixed)

    def _demo_indices(self, n):
        fixed = self.pools['seed'].buffer.size()
        total = fixed + self.pools['interventions'].buffer.size()
        if not total:
            raise RuntimeError('no human demonstrations available')
        ids = np.random.randint(total, size=n)
        return [('seed', ids[ids < fixed]), ('interventions', ids[ids >= fixed]-fixed)]

    def _samples(self, selections, env=None):
        self._ensure()
        chunks = []
        for name, ids in selections:
            if not len(ids):
                continue
            b = self.pools[name].buffer
            chunks.append(({k: a[ids, 0].copy() for k, a in b.observations.items()},
                {k: a[ids, 0].copy() for k, a in b.next_observations.items()},
                b.actions[ids, 0].copy(), b.rewards[ids, 0, None].copy(),
                (b.dones[ids, 0]*(1-b.timeouts[ids, 0]))[:, None]))
        order = np.random.permutation(sum(len(c[2]) for c in chunks))
        raw = [{k: np.concatenate([c[i][k] for c in chunks])[order] for k in chunks[0][i]} for i in (0, 1)]
        raw.extend(np.concatenate([c[i] for c in chunks])[order] for i in (2, 3, 4))
        return self.pools['online'].buffer._to_samples(raw, env)

    def sample_human(self, batch_size, env=None):
        self._ensure()
        if batch_size < 1:
            raise ValueError('positive batch size required')
        return self._samples(self._demo_indices(batch_size), env)

    def sample(self, batch_size, env=None):
        self._ensure()
        if batch_size < 2 or batch_size % 2:
            raise ValueError('dual 50/50 sampling requires an even batch size >= 2')
        n = self.pools['online'].buffer.size()
        if not n:
            raise RuntimeError('online buffer empty; only explicit critic warmup may use demo-only batches')
        return self._samples(self._demo_indices(batch_size//2) + [('online', np.random.randint(n, size=batch_size//2))], env)

    def checkpoint(self):
        self._ensure()
        for pool in self.pools.values():
            pool.buffer.checkpoint()
        atomic(self.directory/'manifest.json', self._manifest(True))
        self.dirty = False

    def _release(self):
        for pool in self.pools.values():
            pool.buffer._stop_runtime()
        self.owner.close()
        self.closed = True

    def close(self):
        if self.closed:
            return
        try:
            if not self.failed:
                self.checkpoint()
        finally:
            self._release()

    def import_ready(self, run):
        from omi_hil_rl.hil.exchange import read_episode
        run = Path(run)
        journal = run/'import_pending.json'
        if journal.exists():
            pending = json.loads(journal.read_text())
            if self.dirty or self.last_import != pending:
                raise RuntimeError('unfinished dual import; restore a clean replay backup')
            atomic(Path(pending['directory'])/'imported.json', pending)
            journal.unlink()
        imported = 0
        for ready in sorted((run/'episodes').glob('*/ready.json')):
            if (ready.parent/'imported.json').exists():
                continue
            manifest = json.loads(ready.read_text())
            if manifest['contract'] != self.contract or not manifest['keep'] or manifest['origin'] != 'online':
                raise ValueError('dual runtime import requires matching kept online episode')
            if not 1 <= manifest['count'] <= self.buffer_size:
                raise ValueError('episode exceeds online capacity')
            for record in read_episode(ready.parent, manifest):
                self.validate(record, origin='online')
            pending = dict(backend=VERSION, directory=str(ready.parent.resolve()),
                           episode=manifest['episode'], count=manifest['count'])
            atomic(journal, pending)
            try:
                for record in read_episode(ready.parent, manifest):
                    self.append(record)
                self.last_import = pending
                self.checkpoint()
            except BaseException:
                self.failed = True  # close must not bless a partial multi-store import
                raise
            atomic(ready.parent/'imported.json', pending)
            journal.unlink()
            imported += manifest['count']
        return imported


def open_replay(directory, *, expected_contract=None, prefetch=None):
    manifest = json.loads((Path(directory)/'manifest.json').read_text())
    from .cached_replay import CachedDualReplay, VERSION as CACHED_VERSION
    if manifest.get('backend') == CACHED_VERSION:
        return CachedDualReplay.reopen(directory, expected_contract=expected_contract,
                                       prefetch=True if prefetch is None else prefetch)
    cls = DualTransitionReplay if manifest.get('backend') == VERSION else TransitionReplay
    return cls.reopen(directory, expected_contract=expected_contract, prefetch=False if prefetch is None else prefetch)
