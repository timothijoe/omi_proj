#!/usr/bin/env python3
"""Plot recorded minibatch losses from EEF BC reports without retraining."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refuse to overwrite figure')
    fig, ax = plt.subplots(figsize=(10, 5.8), layout='constrained')
    for path in args.reports:
        report = json.loads(path.read_text())
        rows = report['losses']
        steps = np.asarray([row['step'] for row in rows])
        loss = np.asarray([row['normalized_mse'] for row in rows])
        if not len(rows) or not np.isfinite(loss).all() or np.any(np.diff(steps) <= 0):
            raise ValueError('Invalid recorded losses')
        mode = report['contract'].get('wrist_camera', 'v1 single camera')
        label = f'Wrist {mode} | {report["samples"]} samples'
        dropout = report['contract'].get('wrist_training_dropout', 0.)
        if dropout:
            label += f' | {dropout:.0%} wrist dropout'
        ax.plot(steps, loss, marker='o', markersize=4, linewidth=1.6, label=label)
    ax.set(title='bag_004 | BC training loss', xlabel='Optimizer step',
           ylabel='Normalized action MSE (sampled training minibatch)')
    ax.set_ylim(bottom=0)
    ax.grid(alpha=.22)
    ax.legend(fontsize=9)
    fig.supxlabel('Recorded every 25 steps plus the final step; raw points, no smoothing.\n'
                  'Single-trajectory fitting; no held-out validation curve.', fontsize=10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=170)
    plt.close(fig)
    print(args.output)


if __name__ == '__main__':
    main()
