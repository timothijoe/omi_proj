"""Explicitly export an overfit diagnostic for supervised BC evaluation, offline."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from .behavior_cloning import predict
from .bc_rollout import prepare
from .exchange import atomic_json, atomic_torch, read_episode
from .networks import Actor, VERSION
from omi_hil_rl.training.eef_bc_data import sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--diagnostic', type=Path, required=True)
    p.add_argument('--export', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = p.parse_args()
    if args.export.exists() or args.output.exists():
        p.error('export and output must be new directories')
    torch.set_num_threads(2)
    report = json.loads((args.diagnostic.parent/'report.json').read_text())
    state = torch.load(args.diagnostic, map_location='cpu', weights_only=True)
    if not state.get('diagnostic_only') or not report['same_data_train_and_evaluate']:
        raise ValueError('expected overfit diagnostic')
    original = Path(report['checkpoint'])
    if sha256(original) != report['checkpoint_sha256']:
        raise ValueError('original checkpoint changed')
    index = json.loads((original.parent/'dataset.json').read_text())
    entries = [e for e in index['episodes'] if Path(e['path']).resolve() == Path(report['source_episode']).resolve()]
    if len(entries) != 1 or entries[0]['manifest']['contract'] != state['contract']:
        raise ValueError('source episode/contract mismatch')
    entry = entries[0]
    episode = Path(entry['path'])
    if sha256(episode/'ready.json') != entry['manifest_sha256']:
        raise ValueError('source manifest changed')
    for i, checksum in enumerate(entry['sample_sha256']):
        if sha256(episode/f'{i:06d}.npz') != checksum:
            raise ValueError('source sample changed')
    records = list(read_episode(episode, entry['manifest']))
    observations = {k: np.stack([r['observation'][k] for r in records]) for k in records[0]['observation']}
    labels = np.stack([r['executed_action'] for r in records])
    del records
    actor = Actor(state['recipe']).to(args.device).eval()
    actor.load_state_dict(state['actor'], strict=True)
    prediction = predict(actor, observations, 16, args.device)
    with np.load(args.diagnostic.parent/'trainable_encoder_and_head_predictions.npz') as saved:
        print('RELOAD_CHECK: '+json.dumps(dict(max_abs_difference=float(np.max(np.abs(prediction-saved['prediction']))),
            device=args.device, mse=float(np.mean((prediction-labels)**2)), labels_equal=bool(np.array_equal(labels, saved['target'])))), flush=True)
        if not np.array_equal(labels, saved['target']) or not np.allclose(prediction, saved['prediction'], atol=1e-4, rtol=1e-4):
            raise ValueError('reloaded predictions disagree with diagnostic results')
    updates = report['original_version'] + report['modes']['trainable_encoder_and_head']['update']
    if report['refine_from']:
        parent = json.loads((Path(report['refine_from']).parent/'report.json').read_text())
        updates += parent['modes']['trainable_encoder_and_head']['update']
    provenance = dict(kind='single_episode_overfit', source_episode=report['source_episode'],
        source_diagnostic=str(args.diagnostic.resolve()), diagnostic_sha256=sha256(args.diagnostic),
        supervised_evaluation_only=True, generalization_validated=False,
        reload_device=args.device, reloaded_mse=float(np.mean((prediction-labels)**2)))
    args.export.mkdir(parents=True)
    atomic_torch(args.export/'actor.pt', dict(version=VERSION, actor=state['actor'],
        recipe=state['recipe'], contract=state['contract'], updates=updates,
        training_method='behavior_cloning', diagnostic_only=True, overfit_evaluation=provenance))
    atomic_json(args.export/'dataset.json', dict(episodes=entries))
    atomic_json(args.export/'overfit_evaluation.json', provenance)
    prepare(args.export/'actor.pt', args.output, args.device)
    atomic_json(args.output/'overfit_evaluation.json', provenance)
    print('OVERFIT_EVAL_READY: '+json.dumps(dict(provenance, policy_version=updates, output=str(args.output))), flush=True)


if __name__ == '__main__':
    main()
