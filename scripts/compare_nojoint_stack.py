#!/usr/bin/env python3
"""Compare the independent no-joint run with its original joint-input baseline."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    baseline=json.loads((a.baseline/'report.json').read_text())
    current=json.loads((a.run/'report.json').read_text())
    for k in ('source_samples_sha256','validation_samples_sha256','train_episode_ids','validation_episode_ids'):
        assert baseline['config'][k]==current['config'][k],k
    bn,cn=(r['config']['normalization'] for r in (baseline,current))
    for k in bn:
        if k.startswith('state_'):
            np.testing.assert_array_equal(np.array(bn[k])[:,7:],np.array(cn[k])[:,7:])
        else:assert bn[k]==cn[k],k
    with np.load(a.baseline/'history_index.npz') as x,np.load(a.run/'history_index.npz') as y:
        for k in x.files:np.testing.assert_array_equal(x[k],y[k])
    with np.load(a.baseline/'best_validation_predictions.npz') as x,np.load(a.run/'best_validation_predictions.npz') as y:
        for k in ('target','episode','reference_ns'):np.testing.assert_array_equal(x[k],y[k])
    result=dict(same_source_data_labels_history_and_nonjoint_normalization=True,
        baseline=dict(best_step=baseline['best_step'],best=baseline['best_validation'],last=baseline['last_validation']),
        no_joints=dict(best_step=current['best_step'],best=current['best_validation'],last=current['last_validation']),
        relative_best_error_change={k:current['best_validation'][k]/baseline['best_validation'][k]-1 for k in current['best_validation'] if k!='per_axis_rmse'},
        zero=current['zero_baseline'],mean=current['mean_baseline'],
        limitation='Single seed; validation selects best. Baseline CPU vs new CUDA, RNG trajectories and added mask inputs differ; not a matched-device causal ablation. No closed-loop validation.')
    (a.run/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    fig,axes=plt.subplots(1,3,figsize=(15,4.8),layout='constrained')
    for ax,key,scale,title in zip(axes,('normalized_mse','translation_rmse_m','rotation_rmse_rad'),(1,1000,1),('Normalized MSE','Translation component RMSE [mm]','Rotation component RMSE [rad]')):
        for r,name,color in ((baseline,'Original: joints + EEF (CPU)','#3172a8'),(current,'No joints + EEF (CUDA)','#db7724')):
            for split,style in (('train','--'),('validation','-')):
                ax.plot([h['step'] for h in r['history']],[h[split][key]*scale for h in r['history']],style,color=color,label=f'{name} / {split}')
            ax.scatter(r['best_step'],r['best_validation'][key]*scale,color=color,s=30,zorder=4)
        ax.axhline(current['zero_baseline'][key]*scale,color='gray',ls=':',label='Validation zero action')
        ax.set(xlabel='Optimizer step',ylabel=title);ax.grid(alpha=.2)
    axes[0].legend(fontsize=7)
    fig.suptitle('Same data split | single seed 7 | best selected on validation')
    fig.savefig(a.run/'comparison_curves.png',dpi=160);plt.close(fig)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
