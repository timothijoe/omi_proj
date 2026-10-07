"""Build a read-only, BC-specific index from periodic human ready segments."""
import argparse
import json
from pathlib import Path
import random
from types import SimpleNamespace

import numpy as np

from .exchange import atomic_json, read_episode
from .periodic_bc_label import validate_bc_label
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.transition_replay import TransitionReplay, _spaces


def prepare(source, output, *, seed=7):
    source, output = Path(source).resolve(), Path(output).resolve()
    session = json.loads((source/'session.json').read_text())
    if session.get('mode') != 'human_rl_periodic_v1':
        raise ValueError('source is not a periodic human collection session')
    contract = session['contract']
    audits = {p.parent.name: json.loads(p.read_text())
              for p in source.glob('periodic_episodes/*/audit.json')}
    paths = sorted(source.glob('episodes/*/ready.json'))
    if not paths:
        raise ValueError('no ready human segments')
    groups = {p.parent.name.rsplit('-segment-', 1)[0] for p in paths}
    if len(groups) < 2 or not groups <= audits.keys():
        raise ValueError('need two or more audited source episodes for a held-out split')
    successes = sorted(name for name in groups if audits[name]['success'])
    candidates = successes if successes else sorted(groups)
    held = set(random.Random(seed).sample(candidates, min(2, len(candidates), len(groups)-1)))
    observation_space, action_space = _spaces(contract)
    validator = TransitionReplay.__new__(TransitionReplay)
    validator.contract = contract
    validator.buffer = SimpleNamespace(observation_space=observation_space, action_space=action_space)
    entries = []
    for ready in paths:
        directory = ready.parent
        source_episode = directory.name.rsplit('-segment-', 1)[0]
        audit = audits[source_episode]
        manifest = json.loads(ready.read_text())
        if (not audit['training_ready'] or directory.name not in audit['segments'] or
                manifest['contract'] != contract or not manifest['keep'] or
                manifest['count'] < 1 or len(list(directory.glob('*.npz'))) != manifest['count']):
            raise ValueError('unready or incomplete periodic segment: '+str(directory))
        hashes = []
        for record in read_episode(directory, manifest):
            validator.validate(record, origin=manifest['origin'])
            if record['action_source'] != 'human':
                raise ValueError('BC source contains a policy action')
            validate_bc_label(contract, record['executed_action'], record)
            for observation in (record['observation'], record['next_observation']):
                if not observation['history_mask'].all() or not np.all(observation['camera_mask']):
                    raise ValueError('BC source has incomplete observation history')
            hashes.append(sha256(directory/f"{record['step']:06d}.npz"))
        entries.append(dict(path=str(directory), manifest=manifest,
            manifest_sha256=sha256(ready), sample_sha256=hashes,
            source_episode=source_episode,
            split='validation' if source_episode in held else 'training'))
        print(f"BC_INDEX {entries[-1]['split']}: {directory.name} ({manifest['count']})", flush=True)
    if output.exists():
        raise ValueError('use a new output directory')
    output.mkdir(parents=True)
    atomic_json(output/'dataset.json', dict(sources=[str(source)], seed=seed, episodes=entries,
        source_session_sha256=sha256(source/'session.json'),
        split_basis='original_periodic_episode',
        outcome_verification='operator_button_not_independent_visual_confirmation'))
    return dict(segments=len(entries), source_episodes=len(groups),
                samples=sum(e['manifest']['count'] for e in entries), held_out_source_episodes=sorted(held))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, seed=args.seed)), flush=True)


if __name__ == '__main__':
    main()
