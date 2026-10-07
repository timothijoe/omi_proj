"""Offline supervised baseline for the exact HIL actor and command contract.

Reads an immutable offline seed index, never opens replay for writing, never
imports ROS. Exports actor-only BC weights, NOT a trained SAC learner.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from .demo import validate_command_label
from .exchange import atomic_json, atomic_torch, read_episode
from .networks import Actor, VERSION, load_actor
from .shutdown import graceful_stop
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.transition_replay import TransitionReplay, _spaces


def load_data(index, contract):
    validator = TransitionReplay.__new__(TransitionReplay)
    validator.contract = contract
    spaces = _spaces(contract)
    validator.buffer = SimpleNamespace(observation_space=spaces[0], action_space=spaces[1])
    data = {}
    for split in ('training', 'validation'):
        episodes = [e for e in index['episodes'] if e['split'] == split]
        count = sum(e['manifest']['count'] for e in episodes)
        if not count:
            raise ValueError('both episode-disjoint splits required')
        obs = {k: np.empty((count, *s['shape']), dtype=s['dtype'])
               for k, s in contract['observations'].items()}
        actions, ids = np.empty((count, 6), np.float32), []
        offset = 0
        for ep in episodes:
            path = Path(ep['path'])
            if ep['manifest']['contract'] != contract or sha256(path/'ready.json') != ep['manifest_sha256']:
                raise ValueError('source manifest/contract changed')
            previous = None
            for record in read_episode(path, ep['manifest']):
                if sha256(path/f"{record['step']:06d}.npz") != ep['sample_sha256'][record['step']]:
                    raise ValueError('source sample changed')
                validator.validate(record, origin=ep['manifest']['origin'])
                validate_command_label(contract, record['executed_action'], record)
                if record['action_source'] != 'human':
                    raise ValueError('BC accepts human labels only, not policy-generated actions')
                if previous is not None and any(not np.array_equal(previous[k], v)
                                               for k, v in record['observation'].items()):
                    raise ValueError('discontinuous source observations')
                previous = record['next_observation']
                for k in obs:
                    obs[k][offset] = record['observation'][k]
                actions[offset] = record['executed_action']
                ids.append(f"{record['episode']}:{record['step']}")
                offset += 1
            print(f'BC_READ {split}: {path.name}', flush=True)
        data[split] = (obs, actions, ids)
    if set(data['training'][2]) & set(data['validation'][2]):
        raise ValueError('split overlap')
    return data


def metrics(prediction, target, scale):
    difference = prediction-target
    moving_x = np.abs(target[:, 0]) > .05
    zero_rotation = np.max(np.abs(target[:, 3:]), axis=1) < 1e-5
    return dict(samples=len(target), mse=float(np.mean(difference**2)),
        mse_per_axis=np.mean(difference**2, axis=0).tolist(),
        physical_mae_mm_deg=(np.mean(np.abs(difference), axis=0)*scale*
                             np.array([1000]*3+[180/np.pi]*3)).tolist(),
        predicted_mean=prediction.mean(0).tolist(),
        predicted_abs_rotation_mean=np.abs(prediction[:, 3:]).mean(0).tolist(),
        predicted_dx_positive=int((prediction[:, 0] > .01).sum()),
        predicted_dx_negative=int((prediction[:, 0] < -.01).sum()),
        moving_dx_sign_accuracy=float(np.mean(np.sign(prediction[moving_x, 0]) == np.sign(target[moving_x, 0]))) if moving_x.any() else None,
        zero_rotation_false_motion_fraction=float(np.mean(np.max(np.abs(prediction[zero_rotation, 3:]), axis=1) > .1)) if zero_rotation.any() else None)


@torch.inference_mode()
def predict(actor, observations, batch_size, device):
    result = []
    for start in range(0, len(next(iter(observations.values()))), batch_size):
        obs = {k: torch.as_tensor(v[start:start+batch_size], device=device) for k, v in observations.items()}
        result.append(actor.sample(obs, deterministic=True)[0].cpu().numpy())
    prediction = np.concatenate(result)
    if not np.isfinite(prediction).all():
        raise ValueError('nonfinite prediction')
    return prediction


def bc_update(actor, optimizer, obs, labels):
    prediction = actor.sample(obs, deterministic=True)[0]
    loss = (prediction-labels).square().mean()
    if not torch.isfinite(loss):
        raise ValueError('nonfinite BC loss')
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_([p for p in actor.parameters() if p.requires_grad], 5., error_if_nonfinite=True)
    optimizer.step()
    return float(loss.detach())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pretrained', type=Path, default=Path('local/pretrained/serl_resnet10/backbone.pt'))
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--patience', type=int, default=8)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--device', default='cuda', choices=('cuda', 'cpu'))
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.patience) < 1 or args.output.exists():
        parser.error('positive counts and a NEW output directory required')
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable')
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    source = args.seed_run.resolve()
    recipe = json.loads((source/'recipe.json').read_text())
    index = json.loads((source/'dataset.json').read_text())
    contract = index['episodes'][0]['manifest']['contract']
    if recipe['pretrained_sha256'] != sha256(args.pretrained):
        raise ValueError('pretrained backbone mismatch')
    data = load_data(index, contract)
    args.output.mkdir(parents=True, exist_ok=False)
    recipe = deepcopy(recipe)
    recipe['control_head_initialization'] = 'supervised_bc_human_accepted_commands'
    atomic_json(args.output/'dataset.json', index)
    atomic_json(args.output/'recipe.json', recipe)
    atomic_json(args.output/'config.json', contract['config'])
    actor = Actor(recipe).to(args.device).eval()
    actor.encoder.initialize_pretrained(torch.load(args.pretrained, map_location='cpu', weights_only=True))
    # Deterministic BC learns the mean, not a calibrated exploration variance.
    with torch.no_grad():
        actor.head[-1].weight[6:].zero_()
        actor.head[-1].bias[6:].fill_(-2.)
    optimizer = torch.optim.Adam([p for p in actor.parameters() if p.requires_grad], lr=1e-4)
    frozen = {k: v.detach().cpu().clone() for k, v in actor.named_parameters() if not v.requires_grad}
    scale = np.asarray(contract['physical_action_scale'])
    train_obs, target, _ = data['training']
    val_obs, val_target, _ = data['validation']
    baseline = dict(zero=metrics(np.zeros_like(val_target), val_target, scale),
                    training_mean=metrics(np.broadcast_to(target.mean(0), val_target.shape), val_target, scale))
    before = metrics(predict(actor, val_obs, args.batch_size, args.device), val_target, scale)
    best, best_epoch, updates = float('inf'), 0, 0
    history = []
    with graceful_stop() as stop:
        for epoch in range(1, args.epochs+1):
            order = np.random.permutation(len(target))
            losses = []
            for start in range(0, len(order), args.batch_size):
                if stop():
                    break
                ix = order[start:start+args.batch_size]
                obs = {k: torch.as_tensor(v[ix], device=args.device) for k, v in train_obs.items()}
                labels = torch.as_tensor(target[ix], device=args.device)
                losses.append(bc_update(actor, optimizer, obs, labels))
                updates += 1
            state = dict(version=VERSION, recipe=recipe, contract=contract, updates=updates,
                         actor=actor.state_dict(), training_method='behavior_cloning', epoch=epoch,
                         exploration_std_calibrated=False, not_for_autonomous_deployment=True)
            atomic_torch(args.output/'last_actor.pt', state)
            if stop():
                break
            validation = metrics(predict(actor, val_obs, args.batch_size, args.device), val_target, scale)
            row = dict(epoch=epoch, updates=updates, train_batch_mse=float(np.mean(losses)), validation=validation)
            history.append(row)
            atomic_json(args.output/'history.json', history)
            print(json.dumps(row), flush=True)
            if validation['mse'] < best:
                best, best_epoch = validation['mse'], epoch
                atomic_torch(args.output/'actor.pt', state)
            if epoch-best_epoch >= args.patience:
                break
    if not (args.output/'actor.pt').exists():
        print('Stopped before validation; last_actor.pt saved, no selected model.', flush=True)
        return
    loaded, _, _ = load_actor(args.output/'actor.pt', contract, args.device)
    report = dict(method='deterministic_action_mse_bc', source=str(source), best_epoch=best_epoch,
                  optimizer_updates_executed=updates, selection='validation_normalized_action_mse',
                  validation_is_selection_not_independent_test=True, baseline=baseline, before=before,
                  robot_publishers_created=0, critic_trained=False, exploration_std_calibrated=False,
                  frozen_backbone_unchanged=all(torch.equal(frozen[k], v.detach().cpu())
                      for k, v in loaded.named_parameters() if k in frozen))
    for split, (observations, labels, ids) in data.items():
        prediction = predict(loaded, observations, args.batch_size, args.device)
        report[split] = metrics(prediction, labels, scale)
        np.savez_compressed(args.output/f'{split}_predictions.npz', prediction=prediction, target=labels,
                            sample_ids=np.asarray(ids))
    atomic_json(args.output/'report.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
