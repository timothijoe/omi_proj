"""Offline causal 10-slot EEF BC history experiment. No hardware or ROS publishers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random
import time
import numpy as np
import torch
from torch import nn
from .eef_bc_policy import Policy, load_dataset, normalization, inputs
from .eef_bc_data import sha256

VERSION = 'eef-history-v1'
SLOTS = 10
PERIOD_NS = 100_000_000


def history_indices(times, slots=SLOTS):
    """Exact clock slots; -1 means missing. Never compact across missing frames."""
    times = np.asarray(times, dtype=np.int64)
    if times.ndim != 1 or len(times) == 0 or np.any(np.diff(times) <= 0):
        raise ValueError('Expected strictly increasing per-episode reference times')
    lookup = {int(t): i for i, t in enumerate(times)}
    return np.array([[lookup.get(int(t)-(slots-1-j)*PERIOD_NS, -1) for j in range(slots)]
                     for t in times], dtype=np.int64)


def load_history(paths):
    data, manifests = load_dataset(paths)
    version=manifests[0]['contract']['version']
    if version not in ('bag-eef-bc-v3-grid-receive','bag-eef-bc-v4-wrench'):
        raise ValueError('History requires recorder-time grid data')
    indices, episodes, times, pools, offset = [], [], [], [], 0
    for number, (path, manifest) in enumerate(zip(paths, manifests)):
        path=Path(path)
        with np.load(path/'samples.npz', allow_pickle=False) as z:
            ts = z['reference_ns'].copy()
            if np.any(z['source_ns'] > ts[:,None]):raise ValueError('Noncausal input timestamps')
        pool_times=ts
        if version=='bag-eef-bc-v4-wrench':
            from .eef_bc_data import profile_for
            from .eef_bc_policy import validate_cameras
            from .eef_bc_wrench import validate_wrench
            if sha256(path/'history_observations.npz')!=manifest['history_observations_sha256']:
                raise ValueError('History pool hash mismatch')
            with np.load(path/'history_observations.npz',allow_pickle=False) as z:
                pool={k:z[k].copy() for k in profile_for(manifest['contract']).ARRAYS}
                pool_times=z['reference_ns'].copy()
                if np.any(z['source_ns']>pool_times[:,None]):raise ValueError('Noncausal history pool')
            validate_cameras(pool,manifest['contract']);validate_wrench(pool)
            for key,value in pool.items():
                if value.shape[1:]!=data[key].shape[1:] or len(value)!=len(pool_times) or not np.isfinite(value).all():
                    raise ValueError('Invalid history pool '+key)
            selected=np.searchsorted(pool_times,ts)
            if np.any(selected>=len(pool_times)) or not np.array_equal(pool_times[selected],ts):
                raise ValueError('Target missing from history pool')
            # Target observations must agree exactly with the audited samples file.
            with np.load(path/'samples.npz',allow_pickle=False) as z:
                if any(not np.array_equal(value[selected],z[key]) for key,value in pool.items()):
                    raise ValueError('Target/history observation mismatch')
            pools.append(pool)
        else:selected=np.arange(len(ts))
        index=history_indices(pool_times)[selected]
        indices.append(np.where(index>=0,index+offset,-1))
        times.append(ts);episodes.extend([number]*len(ts));offset+=len(pool_times)
    if pools:
        for key in pools[0]:data[key]=np.concatenate([pool[key] for pool in pools])
    return data, manifests, np.concatenate(indices), np.array(episodes), np.concatenate(times)


class HistoryPolicy(nn.Module):
    def __init__(self, base_contract):
        super().__init__()
        self.encoder = Policy(base_contract)
        feature_size = self.encoder.head[0].in_features
        self.encoder.head = nn.Identity()
        self.project = nn.Sequential(nn.Linear(feature_size,128), nn.ReLU())
        self.gru = nn.GRUCell(129,128)
        self.head = nn.Sequential(nn.Linear(128,64),nn.ReLU(),nn.Linear(64,6))

    def encode(self, x):
        return self.project(self.encoder(*x))

    def from_features(self, features, mask):
        hidden = features.new_zeros((len(features),128))
        for j in range(features.shape[1]):
            # Relative time reveals gaps even though missing updates are skipped.
            age = features.new_full((len(features),1),(j-(SLOTS-1))/(SLOTS-1))
            candidate = self.gru(torch.cat([features[:,j],age],dim=1),hidden)
            hidden = torch.where(mask[:,j,None],candidate,hidden)
        return self.head(hidden)

    def forward(self, x, indices):
        mask = indices >= 0
        unique, inverse = torch.unique(indices[mask],sorted=True,return_inverse=True)
        encoded = self.encode(tuple(v[unique] for v in x))
        features = encoded.new_zeros((*indices.shape,128))
        features[mask] = encoded[inverse]
        return self.from_features(features,mask)


def predictions(model,x,index,norm):
    model.eval()
    with torch.inference_mode():
        encoded = torch.cat([model.encode(tuple(v[i:i+64] for v in x)) for i in range(0,len(x[0]),64)])
        results=[]
        for i in range(0,len(index),128):
            ix=index[i:i+128];mask=ix>=0
            features=encoded[ix.clamp_min(0)]*mask[:,:,None]
            results.append(model.from_features(features,mask))
        pred=torch.cat(results).numpy()
    return pred*np.asarray(norm['delta_std'],np.float32)+np.asarray(norm['delta_mean'],np.float32)


def scores(pred,target,norm):
    error=pred-target
    return dict(translation_rmse_m=float(np.sqrt(np.mean(error[:,:3]**2))),
        rotation_rmse_rad=float(np.sqrt(np.mean(error[:,3:]**2))),
        normalized_mse=float(np.mean((error/np.asarray(norm['delta_std'],np.float32))**2)),
        per_axis_rmse=np.sqrt(np.mean(error**2,axis=0)).tolist())


def load_history_policy(path):
    checkpoint=torch.load(path,map_location='cpu',weights_only=True)
    config=checkpoint['config']
    if (config['version'] != VERSION or config['history_slots'] != SLOTS
            or config['period_ns'] != PERIOD_NS):
        raise ValueError('Incompatible history checkpoint')
    model=HistoryPolicy(config['base_contract'])
    model.load_state_dict(checkpoint['state_dict'],strict=True)
    model.eval()
    return model,config['normalization'],checkpoint


def run(plan_path,output,steps=2000,seed=7):
    output=Path(output)
    if output.exists(): raise FileExistsError(output)
    if steps<1: raise ValueError('Positive steps required')
    plan=json.loads(Path(plan_path).read_text())
    for split in ('training','validation'):
        if not isinstance(plan.get(split),list) or not plan[split] or not all(isinstance(p,str) for p in plan[split]):
            raise ValueError(f'{split} must be a nonempty list of dataset paths')
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    data,manifests,idx,ep,ts=load_history(plan['training'])
    val,vm,vi,ve,vt=load_history(plan['validation'])
    contract=manifests[0]['contract']
    if vm[0]['contract']!=contract:raise ValueError('Contract mismatch')
    if {m['episode_id'] for m in manifests}&{m['episode_id'] for m in vm}:raise ValueError('Episode leakage')
    norm=normalization(data);x=inputs(data,norm);vx=inputs(val,norm)
    target=data['action'];vtarget=val['action']
    y=torch.as_tensor((target-np.asarray(norm['delta_mean'],np.float32))/np.asarray(norm['delta_std'],np.float32))
    index=torch.as_tensor(idx);vindex=torch.as_tensor(vi)
    model=HistoryPolicy(contract);optimizer=torch.optim.Adam(model.parameters(),lr=.001)
    output.mkdir(parents=True)
    np.savez_compressed(output/'history_index.npz',train_index=idx,validation_index=vi,
        train_episode=ep,validation_episode=ve,train_reference_ns=ts,validation_reference_ns=vt)
    config=dict(version=VERSION,base_contract=contract,history_slots=SLOTS,period_ns=PERIOD_NS,
        first_to_last_span_s=.9,missing='-1 index; skip encoder and GRU update; relative slot time supplied',
        history_source=('all causal valid inputs, independent of future labels' if 'wrench_shape' in contract else 'retained causal v3 observations only; missing intermediate observations are masked'),
        hidden='reset to zero per window; no cross-window persistent hidden state',
        normalization=norm,train_episode_ids=[m['episode_id'] for m in manifests],
        validation_episode_ids=[m['episode_id'] for m in vm],steps=steps,seed=seed,batch_size=32,
        learning_rate=.001,device='cpu',selection='lowest validation normalized MSE among trained evaluations every100 steps',
        source_samples_sha256=[m['samples_sha256'] for m in manifests],
        validation_samples_sha256=[m['samples_sha256'] for m in vm])
    (output/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    history=[];losses=[];best=float('inf');best_step=None;started=time.monotonic()
    def evaluate(step):
        nonlocal best,best_step
        pred=predictions(model,x,index,norm);vp=predictions(model,vx,vindex,norm)
        row=dict(step=step,train=scores(pred,target,norm),validation=scores(vp,vtarget,norm))
        history.append(row)
        if step>0 and row['validation']['normalized_mse']<best:
            best=row['validation']['normalized_mse'];best_step=step
            torch.save(dict(config=config,step=step,state_dict=model.state_dict()),output/'best.pt')
        (output/'history.json').write_text(json.dumps(history,indent=2)+'\n')
        print(json.dumps(row),flush=True)
        return pred,vp
    evaluate(0)
    for step in range(1,steps+1):
        model.train();batch=torch.randint(len(target),(min(32,len(target)),))
        loss=nn.functional.mse_loss(model(x,index[batch]),y[batch])
        if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
        optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),5.);optimizer.step()
        if step==1 or step%25==0:losses.append(dict(step=step,normalized_mse=float(loss.detach())))
        if step%100==0 or step==steps:pred,vp=evaluate(step)
    torch.save(dict(config=config,step=steps,state_dict=model.state_dict()),output/'last.pt')
    np.savez_compressed(output/'last_predictions.npz',train=pred,validation=vp,
        train_target=target,validation_target=vtarget,validation_episode=ve,validation_reference_ns=vt)
    checkpoint=torch.load(output/'best.pt',map_location='cpu',weights_only=True)
    model.load_state_dict(checkpoint['state_dict']);bp=predictions(model,vx,vindex,norm)
    np.savez_compressed(output/'best_validation_predictions.npz',prediction=bp,target=vtarget,
        episode=ve,reference_ns=vt)
    only_current=vindex.clone();only_current[:,:-1]=-1
    ablation=predictions(model,vx,only_current,norm)
    mean=target.mean(0)
    report=dict(config=config,seconds=time.monotonic()-started,samples=len(target),validation_samples=len(vtarget),
        parameters=sum(p.numel() for p in model.parameters()),history=history,losses=losses,best_step=best_step,
        best_validation=scores(bp,vtarget,norm),last_validation=history[-1]['validation'],
        zero_baseline=scores(np.zeros_like(vtarget),vtarget,norm),mean_baseline=scores(np.broadcast_to(mean,vtarget.shape),vtarget,norm),
        best_with_history_masked_at_inference=scores(ablation,vtarget,norm),
        history_valid_slots_train=dict(zip(*[a.tolist() for a in np.unique((idx>=0).sum(1),return_counts=True)])),
        history_valid_slots_validation=dict(zip(*[a.tolist() for a in np.unique((vi>=0).sum(1),return_counts=True)])),
        best_sha256=sha256(output/'best.pt'),last_sha256=sha256(output/'last.pt'),
        warning='Validation used for checkpoint selection; not independent test. No physical control, no blockage labels.')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--steps',type=int,default=2000);p.add_argument('--seed',type=int,default=7)
    a=p.parse_args();run(a.plan,a.output,a.steps,a.seed)

if __name__=='__main__':main()
