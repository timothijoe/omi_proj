"""Prepare a NEW protected asynchronous RL run from BC; never opens robot output."""
import argparse
import json
from pathlib import Path

import torch

from .config import HILConfig
from .exchange import atomic_json, publish, read_episode
from .networks import SAC
from .demo import validate_command_label
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.dual_replay import DualTransitionReplay, VERSION as REPLAY_VERSION


def prepare(bc_run, run, *, capacity=4000, intervention_capacity=2000, warmup=1000, bc_weight=10., actor_lr=1e-5, device='cpu'):
    bc_run, run = Path(bc_run).resolve(), Path(run).resolve()
    if run.exists():
        raise ValueError('use a new RL run; existing BC/RL runs are never overwritten')
    state = torch.load(bc_run/'actor.pt', map_location='cpu', weights_only=True)
    if state.get('training_method') != 'behavior_cloning':
        raise ValueError('a behavior-cloning checkpoint is required')
    config = HILConfig(**json.loads((bc_run/'config.json').read_text()))
    if state['contract'] != config.replay_contract():
        raise ValueError('BC config/contract mismatch')
    dataset = json.loads((bc_run/'dataset.json').read_text())
    entries = [e for e in dataset['episodes'] if e.get('split') == 'training']
    if not entries or min(capacity, intervention_capacity) < 1:
        raise ValueError('training samples and positive capacities required')
    if len({e['manifest']['episode'] for e in entries}) != len(entries):
        raise ValueError('duplicate seed episode')
    agent = SAC(state['recipe'], state['contract'], device=device, freeze_encoder=True,
                critic_warmup_updates=warmup, bc_weight=bc_weight, actor_learning_rate=actor_lr)
    agent.initialize_bc(state, provenance=dict(path=str(bc_run/'actor.pt'), sha256=sha256(bc_run/'actor.pt'),
                                               bc_version=state['updates']))
    # Bitwise parameter identity, including normalizer buffers, before any RL updates.
    for key, value in state['actor'].items():
        if not torch.equal(agent.actor.state_dict()[key].cpu(), value):
            raise ValueError('BC transfer changed actor parameters: '+key)
    run.mkdir(parents=True)
    atomic_json(run/'initializing.json', dict(bc=str(bc_run), protection='frozen_encoder_critic_warmup_bc_anchor'))
    replay = DualTransitionReplay(run/'replay', config.replay_contract(),
        seed_capacity=sum(e['manifest']['count'] for e in entries),
        online_capacity=capacity, intervention_capacity=intervention_capacity)
    count = 0
    try:
        for entry in entries:
            path, manifest = Path(entry['path']), entry['manifest']
            if manifest['contract'] != config.replay_contract() or not manifest['keep']:
                raise ValueError('seed contract/outcome mismatch')
            if sha256(path/'ready.json') != entry['manifest_sha256']:
                raise ValueError('seed manifest changed')
            hashes = entry['sample_sha256']
            if len(hashes) != manifest['count']:
                raise ValueError('incomplete seed hash list')
            for record in read_episode(path, manifest):
                if sha256(path/f"{record['step']:06d}.npz") != hashes[record['step']]:
                    raise ValueError('seed sample changed')
                validate_command_label(config.replay_contract(), record['executed_action'], record)
                if record['action_source'] != 'human':
                    raise ValueError('BC anchor seed must contain human actions')
                replay.append_seed(record, origin=manifest['origin'])
                count += 1
        replay.seal_seed()
        streams = replay.buffer.stream_counts()
    finally:
        replay.close()
    atomic_json(run/'config.json', state['contract']['config'])
    atomic_json(run/'recipe.json', state['recipe'])
    atomic_json(run/'dataset.json', dict(dataset, episodes=entries))
    publish(run, agent)
    report = dict(samples=count, episodes=len(entries), streams=streams,
                  initial_actor_exact=True, bc_version=state['updates'], rl_version=0,
                  critic_warmup_updates=warmup, bc_weight=bc_weight, actor_learning_rate=actor_lr,
                  encoder_frozen=True, historical_seed_is_not_new_robot_experience=True)
    atomic_json(run/'bc_initialization.json', report)
    # This marker is last: a failed preparation cannot be launched as a session.
    atomic_json(run/'async_session.json', dict(mode='async_hil_v1', seed=str(bc_run),
        contract=config.replay_contract(), control_mode='periodic_training_v1',
        reset_actions_in_replay=False, policy_selection='latest_validated_not_best', replay_capacity=capacity,
        replay_backend=REPLAY_VERSION, intervention_capacity=intervention_capacity))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bc-run', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--capacity', type=int, default=4000)
    p.add_argument('--intervention-capacity', type=int, default=2000)
    p.add_argument('--critic-warmup-updates', type=int, default=1000)
    p.add_argument('--bc-weight', type=float, default=10.)
    p.add_argument('--actor-learning-rate', type=float, default=1e-5)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    a = p.parse_args()
    torch.set_num_threads(2)
    print(json.dumps(prepare(a.bc_run, a.run, capacity=a.capacity, warmup=a.critic_warmup_updates,
                            bc_weight=a.bc_weight, actor_lr=a.actor_learning_rate, device=a.device,
                            intervention_capacity=a.intervention_capacity)), flush=True)


if __name__ == '__main__':
    main()
