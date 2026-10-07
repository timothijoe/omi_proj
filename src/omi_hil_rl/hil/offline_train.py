"""Offline SAC pipeline over recorded episodes. No ROS imports or robot output."""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import shutil
import time
from types import SimpleNamespace

import numpy as np
import torch

from .config import HILConfig
from .exchange import atomic_json, owner_lock, publish, read_episode
from .networks import SAC, load_actor
from .shutdown import graceful_stop
from omi_hil_rl.training.transition_replay import TransitionReplay, _spaces
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.hil.demo import validate_command_label


def split_episodes(source, seed):
    sources = [source] if isinstance(source, Path) else list(source)
    if not sources or len({p.resolve() for p in sources}) != len(sources):
        raise ValueError('provide distinct nonempty source directories')
    session = json.loads((sources[0] / 'session.json').read_text())
    contract = session['contract']
    config = HILConfig(**session['config'])
    if config.replay_contract() != contract:
        raise ValueError('session config/contract mismatch')
    episodes = []
    seen = set()
    for directory in sources:
        other = json.loads((directory/'session.json').read_text())
        if other['contract'] != contract or HILConfig(**other['config']).replay_contract() != contract:
            raise ValueError('source session contracts differ')
        for path in sorted(directory.glob('episodes/*/ready.json')):
            manifest = json.loads(path.read_text())
            if manifest['contract'] != contract or not manifest['keep'] or manifest['count'] < 1:
                raise ValueError('invalid ready manifest: ' + str(path))
            if len(list(path.parent.glob('*.npz'))) != manifest['count']:
                raise ValueError('episode sample count mismatch')
            if manifest['episode'] in seen:
                raise ValueError('duplicate episode across sources: ' + manifest['episode'])
            seen.add(manifest['episode'])
            episodes.append((path.parent, manifest))
    # Reserve one success and one non-success, leaving both represented in training.
    rng = random.Random(seed)
    held = set()
    for success in (True, False):
        group = [m['episode'] for _, m in episodes if m['episode_success'] == success]
        if len(group) >= 2:
            held.add(rng.choice(group))
    training = [(p, m) for p, m in episodes if m['episode'] not in held]
    validation = [(p, m) for p, m in episodes if m['episode'] in held]
    if not training or not validation:
        raise ValueError('need enough complete episodes for a disjoint held-out split')
    return config, contract, training, validation


def prepare(source, output, pretrained, seed):
    config, contract, training, validation = split_episodes(source, seed)
    obs_space, action_space = _spaces(contract)
    validator = TransitionReplay.__new__(TransitionReplay)
    validator.contract = contract
    validator.buffer = SimpleNamespace(observation_space=obs_space, action_space=action_space)
    sums = {'tactile': np.zeros(10), 'state': np.zeros(14)}
    squares = {k: np.zeros_like(v) for k, v in sums.items()}
    counts = Counter()
    index = []
    for split, episodes in [('training', training), ('validation', validation)]:
        for directory, manifest in episodes:
            previous = None
            hashes = []
            for record in read_episode(directory, manifest):
                validator.validate(record, origin=manifest['origin'])
                if record['action_source'] != 'human':
                    raise ValueError('this offline entry expects human collection')
                validate_command_label(contract, record['executed_action'], record)
                obs, nxt = record['observation'], record['next_observation']
                for window in (obs, nxt):
                    if not window['history_mask'].all() or not (window['camera_mask'] == 1).all():
                        raise ValueError('incomplete observation history/cameras')
                if previous is not None and not all(np.array_equal(previous[k], obs[k]) for k in obs):
                    raise ValueError('non-contiguous episode observation arrays')
                previous = nxt
                final = record['step'] == manifest['count'] - 1
                success = manifest['episode_success']
                if record['reward'] != float(final and success) or record['terminated'] != (final and success) or record['truncated'] != (final and not success):
                    raise ValueError('inconsistent outcome labels')
                hashes.append(sha256(directory / f"{record['step']:06d}.npz"))
                if split == 'training':
                    values = dict(tactile=obs['tactile'].astype(np.float64).transpose(0, 2, 3, 1).reshape(-1, 10),
                                  state=obs['state'].astype(np.float64).reshape(-1, 14))
                    for key, arr in values.items():
                        sums[key] += arr.sum(0)
                        squares[key] += np.square(arr).sum(0)
                        counts[key] += len(arr)
            index.append(dict(path=str(directory.resolve()), manifest=manifest,
                              manifest_sha256=sha256(directory/'ready.json'), split=split, sample_sha256=hashes))
            print(f"validated {split}: {manifest['episode']} ({manifest['count']} samples)", flush=True)
    normalization = {}
    for key, floor, shape in [('tactile', 1e-4, (1, 10, 1, 1)), ('state', 1e-3, (1, 14))]:
        mean = sums[key]/counts[key]
        std = np.maximum(np.sqrt(np.maximum(squares[key]/counts[key] - mean**2, 0)), floor)
        if key == 'state':
            mean[:7], std[:7] = 0, 1
        normalization[key+'_mean'] = mean.reshape(shape).tolist()
        normalization[key+'_std'] = std.reshape(shape).tolist()
    recipe = dict(encoder='current9stack', base_contract=GridProfile(config.wrist_camera).CONTRACT,
                  normalization=normalization, sdk_convention=config.sdk_convention, wrench_history=False,
                  control_head_initialization='scratch', normalization_source='training_episodes_only',
                  pretrained_sha256=sha256(pretrained))
    atomic_json(output/'config.json', contract['config'])
    atomic_json(output/'recipe.json', recipe)
    sources = [source] if isinstance(source, Path) else list(source)
    atomic_json(output/'dataset.json', dict(sources=[str(p.resolve()) for p in sources], seed=seed, episodes=index,
        labels_assumed_valid=True, outcome_verification='user_assumption_not_visual_verification'))
    return config, contract, recipe, index


@torch.inference_mode()
def evaluate(agent, index):
    """Held-out human-action agreement is a diagnostic, NOT RL policy return."""
    errors, predictions = [], []
    for ep in index:
        if ep['split'] != 'validation':
            continue
        for record in read_episode(ep['path'], ep['manifest']):
            action = agent.act(record['observation'], deterministic=True)
            if not np.isfinite(action).all() or np.any(np.abs(action) > 1):
                raise ValueError('invalid inference output')
            errors.append((action-record['executed_action'])**2)
            predictions.append(action)
    return dict(samples=len(errors), human_action_mse=float(np.mean(errors)),
                predicted_dx_positive=int((np.asarray(predictions)[:, 0] > .01).sum()),
                predicted_dx_negative=int((np.asarray(predictions)[:, 0] < -.01).sum()),
                is_task_success_evaluation=False)


def train(source, output, pretrained, *, updates=100, batch_size=256, seed=7, device='cuda', resume=False,
          should_stop=lambda: False, capacity=None):
    if updates < 2 or batch_size < 2:
        raise ValueError('at least two updates and batch size two required')
    if device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; no implicit fallback')
    np.random.seed(seed)
    torch.manual_seed(seed)
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
    with owner_lock(output, 'learner'):
        if resume:
            state = torch.load(output/'learner.pt', map_location='cpu', weights_only=True)
            contract, recipe = state['contract'], state['recipe']
            index = json.loads((output/'dataset.json').read_text())['episodes']
            agent = SAC.restore(state, device=device, expected_contract=contract)
            replay = TransitionReplay.reopen(output/'replay', expected_contract=contract, prefetch=False)
        else:
            config, contract, recipe, index = prepare(source, output, pretrained, seed)
            required = sum(ep['manifest']['count'] for ep in index if ep['split']=='training')
            if capacity is not None and capacity < required:
                raise ValueError('capacity must fit all initial training records')
            capacity = required if capacity is None else capacity
            bytes_per = 2*sum(np.prod(s['shape'])*np.dtype(s['dtype']).itemsize for s in contract['observations'].values())
            if shutil.disk_usage(output).free < capacity*bytes_per + 2_000_000_000:
                raise RuntimeError('insufficient disk space for replay and checkpoints')
            agent = SAC(recipe, contract, device=device,
                        pretrained=torch.load(pretrained, map_location='cpu', weights_only=True))
            replay = TransitionReplay(output/'replay', contract, capacity, prefetch=False)
        try:
            if not resume:
                for ep in index:
                    if ep['split'] != 'training':
                        continue
                    for record in read_episode(ep['path'], ep['manifest']):
                        path = Path(ep['path']) / f"{record['step']:06d}.npz"
                        if sha256(path) != ep['sample_sha256'][record['step']]:
                            raise ValueError('source changed during import')
                        replay.append(record, origin=ep['manifest']['origin'])
                replay.buffer.checkpoint()
            counts = replay.buffer.stream_counts()
            if min(counts['online'], counts['demonstration']) < 1:
                raise ValueError('both replay streams required')
            publish(output, agent)
            if should_stop():
                return dict(stopped=True, final_update=agent.updates)
            initial = {k: v.detach().cpu().clone() for k, v in agent.actor.named_parameters()}
            frozen = {k: v.detach().cpu().clone() for k, v in agent.actor.named_parameters() if not v.requires_grad}
            before = evaluate(agent, index)
            start_update = agent.updates
            publish(output, agent)
            started = time.monotonic()
            with (output/'metrics.jsonl').open('a') as log:
                for _ in range(updates):
                    if should_stop():
                        break
                    metrics = agent.update(replay.buffer.sample(batch_size))
                    metrics.update(elapsed_seconds=time.monotonic()-started, streams=counts)
                    log.write(json.dumps(metrics, allow_nan=False)+'\n')
                    log.flush()
                    if agent.updates % 10 == 0:
                        atomic_json(output/'status.json', metrics)
                        print(json.dumps(metrics), flush=True)
                    if agent.updates % 50 == 0:
                        publish(output, agent)
            # Save BEFORE slow held-out diagnostics, including an interrupt stop.
            publish(output, agent)
            if should_stop():
                status = dict(stopped=True, start_update=start_update, final_update=agent.updates,
                              updates_this_run=agent.updates-start_update, checkpoint_saved=True)
                atomic_json(output/'status.json', status)
                print(json.dumps(status), flush=True)
                return status
            after = evaluate(agent, index)
            publish(output, agent)
            probe_ep = next(ep for ep in index if ep['split']=='validation')
            probe = next(read_episode(probe_ep['path'], probe_ep['manifest']))['observation']
            expected = agent.act(probe, deterministic=True)
            loaded, version, _ = load_actor(output/'actor.pt', contract, device)
            actual = loaded.sample(agent.observation(probe, single=True), deterministic=True)[0][0].detach().cpu().numpy()
            error = float(np.max(np.abs(expected-actual)))
            if error > 1e-6:
                raise ValueError('checkpoint reload prediction mismatch')
            changed = any(not torch.equal(initial[k], v.detach().cpu()) for k, v in agent.actor.named_parameters())
            frozen_ok = all(torch.equal(frozen[k], v.detach().cpu()) for k, v in agent.actor.named_parameters() if k in frozen)
            if not changed or not frozen_ok:
                raise ValueError('actor did not update or frozen parameters changed')
            report = dict(start_update=start_update, final_update=agent.updates, updates_this_run=updates,
                batch_size=batch_size, device=device, streams=counts, held_out_before=before, held_out_after=after,
                actor_parameters_changed=changed, frozen_actor_parameters_unchanged=frozen_ok,
                actor_reload_max_abs_error=error, reloaded_version=version,
                peak_cuda_bytes=torch.cuda.max_memory_allocated() if device=='cuda' else None,
                robot_publishers_created=0, labels_assumed_valid=True, not_for_robot_deployment=True)
            atomic_json(output/f'report_{agent.updates:06d}.json', report)
            atomic_json(output/'report.json', report)
            print(json.dumps(report, indent=2), flush=True)
            return report
        finally:
            replay.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, nargs='+', default=[Path('local/rl_episodes/collect_20261006_001958')],
                   help='one or more matching collection sessions; snapshotted on new runs')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--pretrained', type=Path, default=Path('local/pretrained/serl_resnet10/backbone.pt'))
    p.add_argument('--updates', type=int, default=100)
    p.add_argument('--batch-size', type=int, default=256)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--capacity', type=int, help='reserve replay capacity for later online episodes')
    args = p.parse_args()
    torch.set_num_threads(2)
    with graceful_stop() as should_stop:
        train([p.resolve() for p in args.source], args.output.resolve(), args.pretrained.resolve(), updates=args.updates,
              batch_size=args.batch_size, seed=args.seed, device=args.device, resume=args.resume,
              should_stop=should_stop, capacity=args.capacity)


if __name__ == '__main__':
    main()
