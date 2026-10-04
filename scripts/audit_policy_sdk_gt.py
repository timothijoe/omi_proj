#!/usr/bin/env python3
"""Check saved GT increments and SDK-frame target equivalence; no ROS/hardware."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from omi_hil_rl.training.eef_action import between
from omi_hil_rl.real.eef_reference import reference_pose
from omi_hil_rl.real.policy_action import SDK_FROM_POLICY,SDK_CONVENTION
from omi_hil_rl.real.sdk_action import output_action


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();plan=json.loads(args.plan.read_text());rows=[];Q=SDK_FROM_POLICY
    for path in dict.fromkeys(plan['training']+plan['validation']):
        errors=[];offset_errors=[];translations=[];rotations=[]
        with np.load(Path(path)/'samples.npz') as z:
            for state,target,label in zip(z['state'],z['target_pose'],z['action']):
                current=state[-7:].astype(float);target=target.astype(float)
                gt=between(current,target);errors.append(np.max(np.abs(gt-label)))
                shifted=between(reference_pose(current,'bag-baseline-v1'),reference_pose(target,'bag-baseline-v1'))
                offset_errors.append(np.max(np.abs(shifted-gt)))
                wire=np.array(output_action(label,SDK_CONVENTION))
                translations.append(np.linalg.norm(Q@current[:3]+wire[:3]/1000-Q@target[:3]))
                actual=Rotation.from_euler('xyz',wire[3:],degrees=True).as_matrix()@Q@Rotation.from_quat(current[3:]).as_matrix()
                expected=Q@Rotation.from_quat(target[3:]).as_matrix()
                rotations.append(Rotation.from_matrix(actual@expected.T).magnitude())
        row=dict(dataset=path,samples=len(errors),max_stored_gt_error=float(max(errors)),
                 max_constant_offset_delta_error=float(max(offset_errors)),max_sdk_target_position_error_m=float(max(translations)),
                 max_sdk_target_orientation_error_rad=float(max(rotations)))
        assert max(errors)<5e-6 and max(translations)<5e-6 and max(rotations)<5e-6,row
        rows.append(row)
    report=dict(convention=SDK_CONVENTION,sdk_from_policy=Q.tolist(),datasets=rows,
                total_samples=sum(r['samples'] for r in rows),passed=True,
                gt='dp=p_future-p_current, dr=Log(R_future R_current.T); base_link m/rad, nominal100ms',
                wire='dp_mm=1000 Q dp, ABC_deg from Q Exp(dr) Q.T; applied once after arbiter',
                assumptions='same physical TCP, fixed installation Q, SDK FRAME_BASE=0 and aligned UserFrame; not physical calibration')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
