"""Export a retained last.pt only if it is the best evaluated training checkpoint."""
import argparse
import json
from pathlib import Path

import torch

from omi_hil_rl.hil.networks import VERSION
from omi_hil_rl.training.demo_bc import BC_VERSION
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.wrench_live import load_wrench_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    report = json.loads((args.run / 'report.json').read_text())
    best = min(report['history'], key=lambda row: row['training']['normalized_mse'])
    source = args.run / 'last.pt'
    state = torch.load(source, map_location='cpu', weights_only=True)
    if state['version'] != BC_VERSION or state['updates'] != best['step']:
        raise ValueError('Retained last.pt is not the best evaluated training checkpoint')
    if state['contract'] != report['contract']:
        raise ValueError('Report/checkpoint contract mismatch')
    target = args.run / 'actor_train_best.pt'
    payload = dict(version=VERSION, algorithm=BC_VERSION, actor=state['actor'],
        recipe=state['recipe'], contract=state['contract'], updates=state['updates'],
        selection='lowest_evaluated_training_mse_not_validation',
        source_sha256=sha256(source), selection_metrics=best)
    with target.open('xb') as stream:
        torch.save(payload, stream)
    actor, _, loaded = load_wrench_policy(target, 'cpu')
    assert loaded['step'] == best['step']
    assert all(torch.equal(value, actor.state_dict()[key]) for key, value in state['actor'].items())
    print(json.dumps(dict(path=str(target), step=best['step'], metrics=best,
                         checkpoint_weights_match=True), indent=2))


if __name__ == '__main__':
    main()
