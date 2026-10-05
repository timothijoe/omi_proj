"""Offline recorded-window reproduction and input replacement sensitivity audit."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from omi_hil_rl.training.wrench_live import load_wrench_policy
from omi_hil_rl.training.eef_bc_data import sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();torch.set_num_threads(4)
    manifest=json.loads((a.session/'policy/manifest.json').read_text())
    assert sha256(manifest['checkpoint'])==manifest['checkpoint_sha256']
    model,norm,_=load_wrench_policy(manifest['checkpoint'],'cuda')
    keys=['rgb','wrist_rgb','tactile','state','camera_mask','history_mask','wrench','wrench_mask']
    def read(path,training=False):
        with np.load(path) as z:
            obs={k:z[('observation__' if training else '')+k].copy() for k in keys}
            return obs,z['action'].copy()
    def infer(observations):
        with torch.inference_mode():
            t={k:torch.as_tensor(np.stack([o[k] for o in observations]),device='cuda') for k in keys}
            return model.sample(t,deterministic=True)[0].cpu().numpy()*model.physical_action_scale
    def zscore(obs,key):
        return (obs[key]-np.asarray(norm[key+'_mean']))/np.asarray(norm[key+'_std'])
    paths=sorted((a.session/'policy/observations').glob('*.npz'));rows=[]
    for start in range(0,len(paths),16):
        batch=[read(x) for x in paths[start:start+16]];pred=infer([o for o,_ in batch])
        for path,(obs,stored),output in zip(paths[start:start+16],batch,pred):
            rows.append(dict(file=str(path),full=bool(obs['history_mask'].all()),
                action_mm=output[:3].tolist(),max_replay_error=float(abs(output-stored).max()),
                state=obs['state'][-1,7:].tolist(),wrench=obs['wrench'][-1].tolist(),
                z_rms={k:float(np.sqrt(np.square(zscore(obs,k)).mean())) for k in ['state','tactile','wrench']},
                wrench_z=zscore(obs,'wrench')[-1].tolist()))
            rows[-1]['action_mm']=(output[:3]*1000).tolist()
    plan=json.loads(a.plan.read_text());train_paths=[];states=[];wrenches=[];train_z={k:[] for k in ['state','tactile','wrench']}
    for ep in plan['training']:
        for path in sorted(Path(ep['path']).glob('*.npz')):
            obs,_=read(path,True);train_paths.append(path);states.append(obs['state'][-1,7:]);wrenches.append(obs['wrench'][-1])
            for k in train_z:train_z[k].append(float(np.sqrt(np.square(zscore(obs,k)).mean())))
    states=np.asarray(states);wrenches=np.asarray(wrenches)
    full=[i for i,r in enumerate(rows) if r['full']];experiments=[]
    for i in sorted(set([full[0],full[len(full)//2],full[-1]])):
        live,_=read(paths[i]);std=np.asarray(norm['state_std']).reshape(14)[7:]
        distance=np.square((states-live['state'][-1,7:])/std).mean(1)
        j=int(distance.argmin());train,target=read(train_paths[j],True)
        variants=[live,train];names=['live','nearest_training_window']
        for k in ['state','wrench','tactile','rgb','wrist_rgb']:
            changed=dict(live);changed[k]=train[k];variants.append(changed);names.append('replace_'+k)
        output=infer(variants)
        experiments.append(dict(live_file=str(paths[i]),nearest_training_file=str(train_paths[j]),
            training_label_mm=(target[:3]*model.physical_action_scale[:3]*1000).tolist(),
            standardized_state_distance=float(np.sqrt(distance[j])),
            actions_mm={n:(v[:3]*1000).tolist() for n,v in zip(names,output)}))
    def span(x):return dict(min=np.min(x,axis=0).tolist(),max=np.max(x,axis=0).tolist(),median=np.median(x,axis=0).tolist())
    result=dict(checkpoint=manifest['checkpoint'],recorded=len(rows),full_windows=len(full),
        max_replay_error_m_rad=max(r['max_replay_error'] for r in rows),
        live_actions_mm=span([r['action_mm'] for r in rows if r['full']]),
        train_state=span(states),live_state=span([r['state'] for r in rows if r['full']]),
        train_wrench=span(wrenches),live_wrench=span([r['wrench'] for r in rows if r['full']]),
        train_z_rms={k:span(v) for k,v in train_z.items()},
        live_z_rms={k:span([r['z_rms'][k] for r in rows if r['full']]) for k in train_z},
        sensitivity=experiments,rows=rows,
        caveat='Input replacements are off-manifold sensitivity probes, not proof of causation or a deployable fix.')
    with a.output.open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__':main()
