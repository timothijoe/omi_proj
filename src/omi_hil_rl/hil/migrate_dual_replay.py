"""Clone a stopped legacy RL session into a new dual-buffer session, offline."""
import argparse
import json
import os
from pathlib import Path
import shutil

import numpy as np
import torch

from .exchange import atomic_json, owner_lock, read_episode
from .config import HILConfig
from .demo import validate_command_label
from omi_hil_rl.training.dual_replay import DualTransitionReplay, VERSION
from omi_hil_rl.training.transition_replay import TransitionReplay, CONTRACT_KEYS
from omi_hil_rl.training.eef_bc_data import sha256


def migrate(source, destination, *, intervention_capacity=2000):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source in destination.parents or destination in source.parents:
        raise ValueError('use a new destination outside the source session')
    if intervention_capacity < 1:
        raise ValueError('positive intervention capacity required')
    if not source.is_dir():
        raise ValueError('source session does not exist')
    with owner_lock(source, 'actor'), owner_lock(source, 'learner'):
        if (source/'import_pending.json').exists():
            raise ValueError('resolve pending source import before migration')
        old_manifest = json.loads((source/'replay/manifest.json').read_text())
        if old_manifest.get('backend') == VERSION or not old_manifest.get('clean'):
            raise ValueError('migration requires a clean legacy single-ring replay')
        config = HILConfig(**json.loads((source/'config.json').read_text()))
        contract = config.replay_contract()
        session = json.loads((source/'async_session.json').read_text())
        if session['contract'] != contract:
            raise ValueError('session contract mismatch')
        learner = torch.load(source/'learner.pt', map_location='cpu', weights_only=True)
        actor = torch.load(source/'actor.pt', map_location='cpu', weights_only=True)
        if (learner['contract'] != contract or actor['contract'] != contract or
                actor['updates'] != learner['updates'] or actor['recipe'] != learner['recipe'] or
                any(not torch.equal(v, actor['actor'][k]) for k, v in learner['actor'].items())):
            raise ValueError('source learner and actor must be matching checkpoints')
        del learner, actor
        dataset = json.loads((source/'dataset.json').read_text())
        entries = [e for e in dataset['episodes'] if e.get('split') == 'training']
        if not entries or len({e['manifest']['episode'] for e in entries}) != len(entries):
            raise ValueError('unique hashed initial training episodes required')
        seed_count = sum(e['manifest']['count'] for e in entries)
        # Approximate destination allocation, plus source archives/checkpoints and margin.
        row_bytes = sum(np.dtype(s['dtype']).itemsize * int(np.prod(s['shape'][1:]))
                        for s in old_manifest['arrays'].values())
        destination.parent.mkdir(parents=True, exist_ok=True)
        required = row_bytes*(seed_count+old_manifest['capacity']+intervention_capacity)
        required += sum(p.stat().st_size for p in source.rglob('*') if p.is_file() and 'replay' not in p.relative_to(source).parts)
        if shutil.disk_usage(destination.parent).free < required+1_000_000_000:
            raise RuntimeError('insufficient disk space for independent dual replay')
        old = TransitionReplay.reopen(source/'replay', expected_contract=contract, prefetch=False)
        new = None
        try:
            destination.mkdir()
            atomic_json(destination/'initializing.json', dict(source=str(source), operation='single_to_dual'))
            new = DualTransitionReplay(destination/'replay', contract, seed_capacity=seed_count,
                online_capacity=old.buffer.buffer_size, intervention_capacity=intervention_capacity)
            seed_ids = set()
            for entry in entries:
                path, manifest = Path(entry['path']), entry['manifest']
                if (manifest['contract'] != contract or not manifest['keep'] or
                        sha256(path/'ready.json') != entry['manifest_sha256'] or
                        len(entry['sample_sha256']) != manifest['count']):
                    raise ValueError('seed manifest/hash mismatch')
                for record in read_episode(path, manifest):
                    if sha256(path/f"{record['step']:06d}.npz") != entry['sample_sha256'][record['step']]:
                        raise ValueError('seed sample hash mismatch')
                    validate_command_label(contract, record['executed_action'], record)
                    new.append_seed(record, origin=manifest['origin'])
                    seed_ids.add((record['episode'], record['step']))
            new.seal_seed()
            online_copied, seed_removed = 0, 0
            b = old.buffer
            slots = [(b.pos+i) % b.buffer_size for i in range(b.size())] if b.full else range(b.size())
            for slot in slots:
                meta = old.metadata(slot)
                if (meta['episode'], meta['step']) in seed_ids:
                    seed_removed += 1
                    continue
                if meta['replay_origin'] != 'online':
                    raise ValueError('unindexed offline demos found; explicit seed provenance required')
                terminated = bool(b.dones[slot, 0] and not b.timeouts[slot, 0])
                record = {k: contract[k] for k in CONTRACT_KEYS}
                record.update(meta, observation={k: a[slot, 0].copy() for k, a in b.observations.items()},
                    next_observation={k: a[slot, 0].copy() for k, a in b.next_observations.items()},
                    executed_action=b.actions[slot, 0].copy(), reward=float(b.rewards[slot, 0]),
                    terminated=terminated, truncated=bool(b.timeouts[slot, 0]), episode_success=terminated)
                new.append(record)
                online_copied += 1
            new.checkpoint()
            report = dict(source=str(source), destination=str(destination), backend=VERSION,
                restored_initial_samples=seed_count, removed_seed_from_online=seed_removed,
                copied_retained_online=online_copied, streams=new.stream_counts(),
                weights_unchanged=True, source_preserved=True)
            new.close()
            new = None
            for name in ('learner.pt', 'actor.pt', 'config.json', 'recipe.json', 'dataset.json', 'bc_initialization.json'):
                if (source/name).exists():
                    shutil.copy2(source/name, destination/name)
            for name in ('episodes', 'periodic_episodes'):
                if (source/name).exists():
                    shutil.copytree(source/name, destination/name)
            # Make independent copied artifacts durable before exposing session marker.
            from .exchange import sync_directory
            for path in destination.rglob('*'):
                if path.is_file() and 'replay' not in path.relative_to(destination).parts:
                    with path.open('rb') as stream:
                        os.fsync(stream.fileno())
            for path in sorted((p for p in destination.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                sync_directory(path)
            # All historical seed IDs now belong exclusively to the fixed area.
            for ready in (destination/'episodes').glob('*/ready.json'):
                manifest = json.loads(ready.read_text())
                ids = {(manifest['episode'], i) for i in range(manifest['count'])}
                if ids and ids <= seed_ids:
                    atomic_json(ready.parent/'imported.json', dict(migrated_to_fixed_seed=True))
            atomic_json(destination/'dual_migration.json', report)
            atomic_json(destination/'async_session.json', dict(session, replay_backend=VERSION,
                migrated_from=str(source), intervention_capacity=intervention_capacity))
            return report
        finally:
            if new is not None:
                new.close()
            old.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--intervention-capacity', type=int, default=2000)
    a = p.parse_args()
    torch.set_num_threads(2)
    print(json.dumps(migrate(a.source, a.run, intervention_capacity=a.intervention_capacity)), flush=True)


if __name__ == '__main__':
    main()
