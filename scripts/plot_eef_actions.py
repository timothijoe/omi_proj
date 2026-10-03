#!/usr/bin/env python3
"""Plot saved EEF proxy labels and same-segment predictions; no ROS or hardware."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('run',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refuse to overwrite figure')
    manifest=json.loads((args.dataset/'manifest.json').read_text())
    report=json.loads((args.run/'report.json').read_text())
    if manifest['contract']!=report['contract'] or manifest['episode_id'] not in report['train_episode_ids']:
        raise ValueError('Dataset does not match training run')
    with np.load(args.dataset/'samples.npz',allow_pickle=False) as data:
        time=(data['reference_ns']-manifest['start_ns'])/1e9
        target=data['action'].copy()
    with np.load(args.run/'train_predictions.npz',allow_pickle=False) as data:
        prediction=data['prediction'].copy()
        if not np.array_equal(data['target'],target):
            raise ValueError('Use a single-episode training run matching this dataset')
    fig,axes=plt.subplots(3,2,figsize=(12,8),sharex=True,layout='constrained')
    for i,ax in enumerate(axes.T.flat):
        scale=1000 if i<3 else 180/np.pi
        ax.plot(time,target[:,i]*scale,color='#2868ad',label='Future recorded pose change')
        ax.plot(time,prediction[:,i]*scale,color='#df6627',ls='--',label='BC prediction')
        ax.axhline(0,color='#8a929c',lw=.7,label='Hold (zero increment)')
        ax.set_ylabel(('dx','dy','dz','rx','ry','rz')[i]+(' [mm]' if i<3 else ' [deg, rotvec]'))
        ax.grid(alpha=.2)
    axes[2,0].set_xlabel('Reference time in bag [s]')
    axes[2,1].set_xlabel('Reference time in bag [s]')
    axes[0,0].legend(fontsize=8,loc='best')
    fig.suptitle('Left EEF base-frame increments | ~100 ms horizon\nSingle-segment fit to future-state proxy labels; no closed-loop evaluation',fontsize=13)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output,dpi=160)
    plt.close(fig)
    print(args.output)

if __name__=='__main__':
    main()
