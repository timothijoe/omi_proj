#!/usr/bin/env python3
"""Compare two completed history runs with identical samples and normalization."""
import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--resnet', type=Path, required=True)
    a = p.parse_args()
    old, new = [json.loads((path/'report.json').read_text()) for path in (a.baseline, a.resnet)]
    for key in ('normalization', 'source_samples_sha256', 'validation_samples_sha256',
                'train_episode_ids', 'validation_episode_ids'):
        if old['config'][key] != new['config'][key]:
            raise ValueError('Comparison mismatch: '+key)
    for name in ('train_index', 'validation_index', 'train_reference_ns', 'validation_reference_ns'):
        with np.load(a.baseline/'history_index.npz') as o, np.load(a.resnet/'history_index.npz') as n:
            np.testing.assert_array_equal(o[name], n[name])
    with np.load(a.baseline/'best_validation_predictions.npz') as o, np.load(a.resnet/'best_validation_predictions.npz') as n:
        for key in ('target', 'episode', 'reference_ns'):
            np.testing.assert_array_equal(o[key], n[key])
        np.savez_compressed(a.resnet/'comparison_predictions.npz', cnn_prediction=o['prediction'],
                            resnet_prediction=n['prediction'], target=n['target'],
                            episode=n['episode'], reference_ns=n['reference_ns'])
    result = dict(same_data_normalization_history=True,
                  cnn_best_step=old['best_step'], resnet_best_step=new['best_step'],
                  cnn_best=old['best_validation'], resnet_best=new['best_validation'],
                  cnn_last=old['last_validation'], resnet_last=new['last_validation'],
                  zero=new['zero_baseline'], mean=new['mean_baseline'],
                  relative_best_error_reduction={k: 1-new['best_validation'][k]/old['best_validation'][k]
                      for k in ('translation_rmse_m', 'rotation_rmse_rad', 'normalized_mse')},
                  limitations='One seed, two validation bags used for selection, different visual architecture and pretraining; no auxiliary localization or control validation.')
    (a.resnet/'comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout='constrained')
    for ax, key, scale, title in zip(axes,
            ('normalized_mse', 'translation_rmse_m', 'rotation_rmse_rad'),
            (1, 1000, 1), ('Normalized MSE', 'Translation component RMSE [mm]', 'Rotation component RMSE [rad]')):
        for report, label, color in ((old, 'Small CNN + GRU', '#2474ad'), (new, 'Frozen ResNet-10 + GRU', '#d66324')):
            for split, style in (('validation', '-'), ('train', '--')):
                ax.plot([h['step'] for h in report['history']],
                        [h[split][key]*scale for h in report['history']],
                        color=color, ls=style, label=f'{label}: {split}')
            ax.scatter([report['best_step']], [report['best_validation'][key]*scale], color=color, s=38, zorder=5)
        ax.axhline(new['zero_baseline'][key]*scale, color='gray', ls=':', label='Validation zero baseline')
        ax.set(xlabel='Optimizer step', ylabel=title); ax.grid(alpha=.2)
    axes[0].legend(fontsize=7)
    fig.suptitle('Same oct03 split | seed 7 | dots: checkpoint selected by validation MSE')
    fig.savefig(a.resnet/'comparison_curves.png', dpi=160)
    plt.close(fig)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
