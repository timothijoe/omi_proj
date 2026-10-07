"""Offline single-episode capacity diagnostic; never a deployment checkpoint."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .behavior_cloning import metrics, predict, bc_update
from .demo import validate_command_label
from .exchange import atomic_json, atomic_torch, read_episode
from .networks import load_actor


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episode', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--updates', type=int, default=1000)
    p.add_argument('--head-updates', type=int, default=3000)
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--lr', type=float, default=1e-4)
    p.add_argument('--device', default='cuda', choices=('cuda', 'cpu'))
    p.add_argument('--refine-from', type=Path, help='continue a diagnostic, never a deployment model')
    args = p.parse_args()
    if args.output.exists() or min(args.updates, args.head_updates, args.batch_size, args.lr) <= 0:
        p.error('new output and positive hyperparameters required')
    torch.set_num_threads(2)
    torch.manual_seed(7)
    np.random.seed(7)
    manifest = json.loads((args.episode/'ready.json').read_text())
    if not manifest['keep'] or not manifest['episode_success']:
        raise ValueError('requires kept success-labelled episode')
    records = list(read_episode(args.episode, manifest))
    for record in records:
        validate_command_label(manifest['contract'], record['executed_action'], record)
    obs = {k: np.stack([r['observation'][k] for r in records]) for k in records[0]['observation']}
    labels = np.stack([r['executed_action'] for r in records])
    del records
    fingerprints = {}
    collisions = []
    for i in range(len(labels)):
        digest = hashlib.sha256()
        for k in sorted(obs):
            digest.update(obs[k][i].tobytes())
        key = digest.hexdigest()
        if key in fingerprints and not np.array_equal(labels[i], labels[fingerprints[key]]):
            collisions.append([fingerprints[key], i])
        fingerprints[key] = i
    actor, version, recipe = load_actor(args.checkpoint, manifest['contract'], args.device)
    if args.refine_from:
        diagnostic = torch.load(args.refine_from, map_location=args.device, weights_only=True)
        if not diagnostic.get('diagnostic_only') or diagnostic['contract'] != manifest['contract'] or diagnostic['recipe'] != recipe:
            raise ValueError('incompatible diagnostic continuation')
        actor.load_state_dict(diagnostic['actor'])
    initial = deepcopy(actor.state_dict())
    scale = np.asarray(manifest['contract']['physical_action_scale'])
    args.output.mkdir(parents=True)
    report = dict(diagnostic_only=True, deployment_allowed=False, same_data_train_and_evaluate=True,
                  source_episode=str(args.episode.resolve()), checkpoint=str(args.checkpoint.resolve()),
                  checkpoint_sha256=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
                  original_version=version, samples=len(labels), identical_input_conflicting_labels=collisions,
                  seed=7, learning_rate=args.lr, batch_size=args.batch_size,
                  refine_from=str(args.refine_from) if args.refine_from else None,
                  pretrained_backbone_remains_frozen=True, modes={})
    before = predict(actor, obs, args.batch_size, args.device)
    report['before'] = metrics(before, labels, scale)
    np.savez_compressed(args.output/'before.npz', prediction=before, target=labels)
    # Frozen-feature probe isolates whether the deployed encoder retains distinctions.
    with torch.inference_mode():
        features = torch.cat([actor.encoder({k: torch.as_tensor(v[s:s+args.batch_size], device=args.device)
                              for k, v in obs.items()}) for s in range(0, len(labels), args.batch_size)])
    features = features.clone()
    stages = [('trainable_encoder_and_head', args.updates)] if args.refine_from else [
        ('head_only', args.head_updates), ('trainable_encoder_and_head', args.updates)]
    for mode, limit in stages:
        actor.load_state_dict(initial)
        parameters = list(actor.head.parameters()) if mode == 'head_only' else [p for p in actor.parameters() if p.requires_grad]
        optimizer = torch.optim.Adam(parameters, lr=args.lr)
        history, best, best_state = [], float('inf'), None
        started = time.monotonic()
        for update in range(1, limit+1):
            ix = np.random.choice(len(labels), min(args.batch_size, len(labels)), replace=False)
            y = torch.as_tensor(labels[ix], device=args.device)
            if mode == 'head_only':
                prediction = actor.head(features[ix])[:, :6].tanh()
                loss = (prediction-y).square().mean()
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, 5., error_if_nonfinite=True)
                optimizer.step()
            else:
                batch = {k: torch.as_tensor(v[ix], device=args.device) for k, v in obs.items()}
                bc_update(actor, optimizer, batch, y)
            if update == 1 or update % 50 == 0 or update == limit:
                with torch.inference_mode():
                    prediction = (actor.head(features)[:, :6].tanh().cpu().numpy() if mode == 'head_only'
                                  else predict(actor, obs, args.batch_size, args.device))
                score = metrics(prediction, labels, scale)
                row = dict(update=update, seconds=time.monotonic()-started, **score)
                history.append(row)
                print(json.dumps(dict(mode=mode, update=update, mse=score['mse'],
                    mae=score['physical_mae_mm_deg'], seconds=row['seconds'])), flush=True)
                atomic_json(args.output/(mode+'_history.json'), history)
                if score['mse'] < best:
                    best, best_state = score['mse'], deepcopy(actor.state_dict())
                    report['modes'][mode] = row
                    np.savez_compressed(args.output/(mode+'_predictions.npz'), prediction=prediction, target=labels)
                    atomic_json(args.output/'report.json', report)
                if best < 1e-4:
                    break
        # Deliberately not load_actor-compatible: cannot accidentally deploy this diagnostic.
        atomic_torch(args.output/(mode+'_diagnostic.pt'), dict(diagnostic_only=True,
                     actor=best_state, recipe=recipe, contract=manifest['contract']))
    print('OVERFIT_DONE '+str(args.output), flush=True)


if __name__ == '__main__':
    main()
