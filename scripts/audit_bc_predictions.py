"""Offline per-sample BC predictions versus recorded labels; no ROS publishers."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader
from omi_hil_rl.training.passive_bc import PassiveDataset
from omi_hil_rl.training.wrench_live import load_wrench_policy, infer_wrench_window
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.real.sdk_action import output_action


def summary(rows):
    target=np.array([r['target_mm_rotvec_deg'] for r in rows])
    pred=np.array([r['prediction_mm_rotvec_deg'] for r in rows])
    def signs(v,epsilon):
        return dict(positive=int((v>epsilon).sum()),near_zero=int((abs(v)<=epsilon).sum()),negative=int((v < -epsilon).sum()))
    pos=target[:,0]>.01;neg=target[:,0]<-.01
    return dict(samples=len(rows), target_x_signs=signs(target[:,0],.01),prediction_x_signs=signs(pred[:,0],.01),
        prediction_x_exact_signs=signs(pred[:,0],0),sign_deadband_mm=.01,
        positive_target_predicted_negative=int((pos & (pred[:,0]<-.01)).sum()),
        negative_target_predicted_positive=int((neg & (pred[:,0]>.01)).sum()),
        positive_target_prediction_x_mean=float(pred[pos,0].mean()) if pos.any() else None,
        target_mean=target.mean(0).tolist(),prediction_mean=pred.mean(0).tolist(),
        target_min=target.min(0).tolist(),target_max=target.max(0).tolist(),
        prediction_min=pred.min(0).tolist(),prediction_max=pred.max(0).tolist(),
        rmse=np.sqrt(np.square(pred-target).mean(0)).tolist(),
        normalized_mse=float(np.mean([r['normalized_mse'] for r in rows])),
        max_wire_roundtrip_error=float(max(r['wire_roundtrip_error'] for r in rows)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(4)
    model,norm,checkpoint=load_wrench_policy(a.checkpoint,'cuda')
    plan=json.loads(a.plan.read_text())
    report=dict(checkpoint=str(a.checkpoint),checkpoint_sha256=sha256(a.checkpoint),step=checkpoint['step'],
        units=['mm','mm','mm','rotvec_deg','rotvec_deg','rotvec_deg'],splits={})
    unit=np.array([1000.]*3+[180/np.pi]*3)
    for split in ('training','validation'):
        data=PassiveDataset(plan,split);rows=[];offset=0
        with (a.output/(split+'.jsonl')).open('x') as out:
            for obs,target in DataLoader(data,batch_size=32,shuffle=False):
                with torch.inference_mode():
                    prediction=model.sample({k:v.cuda() for k,v in obs.items()},deterministic=True)[0].cpu().numpy()
                for i,normalized in enumerate(prediction):
                    path=data.index[offset+i]
                    original,label,meta=data.read(path)
                    physical=normalized*model.physical_action_scale
                    target_physical=label*model.physical_action_scale
                    wire=np.array(output_action(target_physical,plan['contract']['config']['sdk_convention']))
                    row=dict(episode=path.parent.name,step=meta['step'],sample=str(path),
                        target_mm_rotvec_deg=(target_physical*unit).tolist(),
                        prediction_mm_rotvec_deg=(physical*unit).tolist(),
                        prediction_sdk_mm_abc=output_action(physical,plan['contract']['config']['sdk_convention']),
                        recorded_wire=meta['wire_action'],
                        wire_roundtrip_error=float(np.max(abs(wire-np.array(meta['wire_action'])))),
                        normalized_mse=float(np.square(normalized-label).mean()))
                    rows.append(row);out.write(json.dumps(row)+'\n')
                offset+=len(prediction)
        results=summary(rows)
        results['episodes']={ep:summary([r for r in rows if r['episode']==ep]) for ep in sorted({r['episode'] for r in rows})}
        results['worst_x_examples']=sorted(rows,key=lambda r:abs(r['prediction_mm_rotvec_deg'][0]-r['target_mm_rotvec_deg'][0]),reverse=True)[:5]
        # Independently call the exact live inference adapter on one stored sample.
        obs,label,_=data.read(data.index[0]);mask=obs.pop('history_mask')
        live,_=infer_wrench_window(model,norm,(obs,mask),torch.device('cuda'))
        results['live_adapter_max_abs_error']=float(np.max(abs(live*unit-np.array(rows[0]['prediction_mm_rotvec_deg']))))
        report['splits'][split]=results
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
