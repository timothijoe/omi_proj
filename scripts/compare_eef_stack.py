#!/usr/bin/env python3
"""Compare CNN/GRU, frozen ResNet/GRU, and current+past9 stack on the same split."""
import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cnn', type=Path, required=True)
    p.add_argument('--gru', type=Path, required=True)
    p.add_argument('--stack', type=Path, required=True)
    a = p.parse_args()
    paths = dict(cnn_gru=a.cnn, resnet_gru=a.gru, current9stack=a.stack)
    reports = {key: json.loads((path/'report.json').read_text()) for key, path in paths.items()}
    ref = reports['resnet_gru']
    combined = {}
    for name, path in paths.items():
        r = reports[name]
        for key in ('normalization', 'source_samples_sha256', 'validation_samples_sha256',
                    'train_episode_ids', 'validation_episode_ids'):
            if r['config'][key] != ref['config'][key]:
                raise ValueError(f'{name}: comparison mismatch {key}')
        with np.load(a.gru/'history_index.npz') as baseline, np.load(path/'history_index.npz') as current:
            for key in baseline.files:
                np.testing.assert_array_equal(baseline[key], current[key])
        with np.load(a.gru/'best_validation_predictions.npz') as baseline, np.load(path/'best_validation_predictions.npz') as current:
            for key in ('target', 'episode', 'reference_ns'):
                np.testing.assert_array_equal(baseline[key], current[key])
                combined[key] = current[key]
            combined[name] = current['prediction']
    np.savez_compressed(a.stack/'comparison_predictions.npz', **combined)
    result = dict(same_data_normalization_history=True,
        models={name: dict(best_step=r['best_step'], best_validation=r['best_validation'],
            last_validation=r['last_validation'], last_training=r['history'][-1]['train'],
            parameters=r['parameters'], trainable_parameters=r.get('trainable_parameters', r['parameters']))
            for name, r in reports.items()}, zero=ref['zero_baseline'], mean=ref['mean_baseline'],
        stack_relative_best_error_change_vs_resnet_gru={key: reports['current9stack']['best_validation'][key]/ref['best_validation'][key]-1
            for key in ('translation_rmse_m', 'rotation_rmse_rad', 'normalized_mse')},
        limitations='One seed, validation-selected best; history stem finetuning, fusion, parameter count and temporal architecture differ simultaneously.')
    (a.stack/'comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), layout='constrained')
    labels = dict(cnn_gru='Small CNN + GRU', resnet_gru='Frozen ResNet-10 + GRU', current9stack='Current + past9 stack, no GRU')
    colors = dict(cnn_gru='#2474ad', resnet_gru='#d66324', current9stack='#30814f')
    for ax, key, scale, title in zip(axes, ('normalized_mse', 'translation_rmse_m', 'rotation_rmse_rad'),
                                    (1, 1000, 1), ('Normalized MSE', 'Translation RMSE [mm]', 'Rotation RMSE [rad]')):
        for name, r in reports.items():
            for split, style in (('validation', '-'), ('train', '--')):
                ax.plot([h['step'] for h in r['history']], [h[split][key]*scale for h in r['history']],
                        color=colors[name], ls=style, label=labels[name]+' / '+split)
            ax.scatter(r['best_step'], r['best_validation'][key]*scale, color=colors[name], s=35, zorder=5)
        ax.axhline(ref['zero_baseline'][key]*scale, color='gray', ls=':', label='Validation zero action')
        ax.set(xlabel='Optimizer step', ylabel=title); ax.grid(alpha=.2)
    axes[0].legend(fontsize=7)
    fig.suptitle('Same oct03 split, seed 7 | dots selected by validation normalized MSE')
    fig.savefig(a.stack/'comparison_curves.png', dpi=160); plt.close(fig)
    with np.load(a.stack/'best_validation_predictions.npz') as z:
        for episode in np.unique(z['episode']):
            keep = z['episode']==episode
            t = (z['reference_ns'][keep]-z['reference_ns'][keep][0])/1e9
            fig, axs = plt.subplots(3, 2, figsize=(12, 8), sharex=True, layout='constrained')
            for i, ax in enumerate(axs.T.flat):
                scale = 1000 if i<3 else 180/np.pi
                ax.plot(t, z['target'][keep, i]*scale, label='Future EEF proxy label')
                ax.plot(t, z['prediction'][keep, i]*scale, label='Current + past9 prediction')
                ax.set_ylabel(('dx','dy','dz','rx','ry','rz')[i]+(' [mm]' if i<3 else ' [deg, rotvec]'))
                ax.grid(alpha=.2)
            axs[0,0].legend(fontsize=8)
            fig.suptitle(f'Validation episode {episode}, best step {reports["current9stack"]["best_step"]}')
            fig.supxlabel('Seconds from first retained reference')
            fig.savefig(a.stack/f'validation_episode_{episode}.png', dpi=150); plt.close(fig)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
