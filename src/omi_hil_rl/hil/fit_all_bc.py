"""Fit all indexed human episodes with coarse/fine BC. No held-out evaluation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

import numpy as np
import torch

from .behavior_cloning import load_data, predict, metrics, bc_update
from .bc_rollout import prepare
from .exchange import atomic_json, atomic_torch
from .networks import load_actor, VERSION
from .shutdown import graceful_stop
from omi_hil_rl.training.eef_bc_data import sha256


def combine_splits(data):
    """Explicitly turn the old validation samples into training samples."""
    first, second = data['training'], data['validation']
    if set(first[2]) & set(second[2]):
        raise ValueError('duplicate sample IDs')
    return ({k: np.concatenate([first[0][k], second[0][k]]) for k in first[0]},
            np.concatenate([first[1], second[1]]), first[2]+second[2])


def evaluate(prediction, target, ids, scale):
    episodes = np.asarray([s.rsplit(':', 1)[0] for s in ids])
    return dict(overall=metrics(prediction, target, scale), episodes={
        name: metrics(prediction[episodes == name], target[episodes == name], scale)
        for name in sorted(set(episodes))})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--prepare-output', type=Path)
    p.add_argument('--coarse-updates', type=int, default=4000)
    p.add_argument('--fine-updates', type=int, default=8000)
    p.add_argument('--eval-every', type=int, default=250)
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    args = p.parse_args()
    if (args.output.exists() or (args.prepare_output and args.prepare_output.exists()) or
            min(args.coarse_updates, args.fine_updates, args.eval_every, args.batch_size) < 1):
        p.error('positive counts and NEW output directories required')
    torch.set_num_threads(2)
    torch.manual_seed(7)
    rng = np.random.default_rng(7)
    checkpoint = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    if checkpoint.get('training_method') != 'behavior_cloning':
        raise ValueError('start from a BC model, not SAC')
    index = json.loads((args.checkpoint.parent/'dataset.json').read_text())
    if len(index['episodes']) != 8:
        raise ValueError('this experiment requires exactly the eight reviewed episodes')
    contract = checkpoint['contract']
    data = load_data(index, contract)  # Original hashes, observations and command receipts validated.
    observations, labels, ids = combine_splits(data)
    del data
    actor, original_version, recipe = load_actor(args.checkpoint, contract, args.device)
    frozen = {k: v.detach().cpu().clone() for k, v in actor.named_parameters() if not v.requires_grad}
    args.output.mkdir(parents=True)
    training_index = deepcopy(index)
    for entry in training_index['episodes']:
        entry['original_split'] = entry['split']
        entry['split'] = 'training'
    training_index['evaluation_note'] = 'all eight episodes used for fitting; no held-out set'
    atomic_json(args.output/'dataset.json', training_index)
    atomic_json(args.output/'recipe.json', recipe)
    atomic_json(args.output/'config.json', contract['config'])
    scale = np.asarray(contract['physical_action_scale'])
    prediction = predict(actor, observations, args.batch_size, args.device)
    baseline = evaluate(prediction, labels, ids, scale)
    np.savez_compressed(args.output/'before_predictions.npz', prediction=prediction, target=labels, sample_ids=ids)
    report = dict(training_method='all_eight_episodes_coarse_fine_bc',
        source_checkpoint=str(args.checkpoint.resolve()), source_sha256=sha256(args.checkpoint),
        episodes=8, samples=len(labels), success_episodes=sum(e['manifest']['episode_success'] for e in index['episodes']),
        same_data_train_and_evaluate=True, generalization_validated=False, learner_enabled=False,
        original_version=original_version, batch_size=args.batch_size, seed=7, before=baseline, stages=[])
    history, total = [], 0
    parameters = [p for p in actor.parameters() if p.requires_grad]
    best = baseline['overall']['mse']
    best_state = deepcopy(actor.state_dict())
    best_update, best_scores = 0, baseline
    def save_best():
        atomic_torch(args.output/'actor.pt', dict(version=VERSION, actor=best_state,
            recipe=recipe, contract=contract, updates=original_version+best_update,
            training_method='behavior_cloning', training_scope='all_eight_episodes_fit',
            generalization_validated=False, not_for_autonomous_deployment=True))
        np.savez_compressed(args.output/'fit_predictions.npz', prediction=prediction, target=labels, sample_ids=ids)
        report.update(best_update=best_update, policy_version=original_version+best_update, after=best_scores)
        atomic_json(args.output/'report.json', report)
    save_best()
    started = time.monotonic()
    with graceful_stop() as stop:
        for stage, updates, lr in [('coarse', args.coarse_updates, 1e-4), ('fine', args.fine_updates, 1e-5)]:
            actor.load_state_dict(best_state)
            optimizer = torch.optim.Adam(parameters, lr=lr)
            report['stages'].append(dict(stage=stage, learning_rate=lr, max_updates=updates,
                                         starts_from_best_update=best_update))
            for update in range(1, updates+1):
                if stop():
                    report['interrupted'] = True
                    atomic_json(args.output/'report.json', report)
                    print('FIT_STOPPED: best checkpoint preserved; no robot publishers', flush=True)
                    return
                ix = rng.choice(len(labels), min(args.batch_size, len(labels)), replace=False)
                bc_update(actor, optimizer, {k: torch.as_tensor(v[ix], device=args.device) for k,v in observations.items()},
                          torch.as_tensor(labels[ix], device=args.device))
                total += 1
                if update == 1 or update % args.eval_every == 0 or update == updates:
                    prediction = predict(actor, observations, args.batch_size, args.device)
                    scores = evaluate(prediction, labels, ids, scale)
                    score = scores['overall']['mse']
                    row = dict(stage=stage, update=total, stage_update=update, seconds=time.monotonic()-started,
                               mse=score, worst_episode_mse=max(v['mse'] for v in scores['episodes'].values()))
                    history.append(row)
                    print(json.dumps(row), flush=True)
                    atomic_json(args.output/'history.json', history)
                    if score < best:
                        best, best_update, best_scores = score, total, scores
                        best_state = deepcopy(actor.state_dict())
                        save_best()
                    if stage == 'fine' and best < 1e-4:
                        break
    actor.load_state_dict(best_state)
    report.update(optimizer_updates_executed=total, elapsed_seconds=time.monotonic()-started,
                  frozen_backbone_unchanged=all(torch.equal(frozen[k], v.detach().cpu())
                      for k,v in actor.named_parameters() if k in frozen))
    # Reload checkpoint and recompute all outputs before preparing an evaluation session.
    reloaded, _, _ = load_actor(args.output/'actor.pt', contract, args.device)
    check = predict(reloaded, observations, args.batch_size, args.device)
    with np.load(args.output/'fit_predictions.npz') as saved:
        difference = float(np.max(np.abs(check-saved['prediction'])))
        if not np.allclose(check, saved['prediction'], atol=1e-4, rtol=1e-4):
            raise ValueError('saved/reloaded predictions mismatch')
    report['reload_max_abs_difference'] = difference
    atomic_json(args.output/'report.json', report)
    if args.prepare_output:
        prepare(args.output/'actor.pt', args.prepare_output, args.device)
        atomic_json(args.prepare_output/'overfit_evaluation.json', dict(kind='all_eight_episodes_fit',
            source_training=str(args.output.resolve()), source_episodes=[e['path'] for e in index['episodes']],
            supervised_evaluation_only=True, generalization_validated=False,
            fit_mse=best, policy_version=report['policy_version']))
    print('FIT_ALL_DONE: '+json.dumps(dict(output=str(args.output), mse=best,
                                        policy_version=report['policy_version'])), flush=True)


if __name__ == '__main__':
    main()
