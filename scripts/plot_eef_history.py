#!/usr/bin/env python3
"""Render temporal BC learning curves and held-out per-axis predictions."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args()
r=json.loads((a.run/'report.json').read_text());hist=r['history'];steps=[h['step'] for h in hist]
fig,axes=plt.subplots(1,3,figsize=(15,4.8),layout='constrained')
for ax,key,scale,label in zip(axes,('normalized_mse','translation_rmse_m','rotation_rmse_rad'),(1,1000,1),('Normalized MSE','Translation component RMSE [mm]','Rotation component RMSE [rad]')):
 for split in ('train','validation'):ax.plot(steps,[h[split][key]*scale for h in hist],label=split)
 for name,color,style in (('zero_baseline','#555555',':'),('mean_baseline','#30945f','-.')):
  ax.axhline(r[name][key]*scale,color=color,ls=style,label='validation '+name)
 ax.axvline(r['best_step'],color='gray',ls='--',label='selected checkpoint')
 ax.set(xlabel='Optimizer step',ylabel=label);ax.grid(alpha=.2)
axes[0].legend(fontsize=8)
fig.suptitle('oct3 | 10 causal history slots + GRU | full-set evaluation, dropout disabled')
fig.savefig(a.run/'learning_curves.png',dpi=160);plt.close(fig)
with np.load(a.run/'best_validation_predictions.npz') as z:
 pred=z['prediction'];target=z['target'];episode=z['episode'];times=z['reference_ns']
for number in np.unique(episode):
 mask=episode==number;t=(times[mask]-times[mask][0])/1e9
 fig,axes=plt.subplots(3,2,figsize=(12,8),sharex=True,layout='constrained')
 for i,ax in enumerate(axes.T.flat):
  scale=1000 if i<3 else 180/np.pi
  ax.plot(t,target[mask,i]*scale,label='Future EEF proxy label',lw=1.1)
  ax.plot(t,pred[mask,i]*scale,label='History BC',lw=1.1)
  ax.axhline(0,color='gray',ls=':',lw=.8)
  ax.set_ylabel(('dx','dy','dz','rx','ry','rz')[i]+(' [mm]' if i<3 else ' [deg, rotvec]'));ax.grid(alpha=.2)
 axes[0,0].legend(fontsize=8);axes[-1,0].set_xlabel('Time from first retained sample [s]');axes[-1,1].set_xlabel('Time from first retained sample [s]')
 fig.suptitle(f'Validation episode {number} | selected step {r["best_step"]} | also used for checkpoint selection')
 fig.savefig(a.run/f'validation_episode_{number}.png',dpi=150);plt.close(fig)
