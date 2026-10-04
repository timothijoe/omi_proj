"""Live no-joint current+past9 inference audit. No ROS action publishers."""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import json
import os
from pathlib import Path
import threading
import time

import numpy as np
import torch

from .eef_bc_stack import load_stack_policy, NO_JOINT_VERSION
from .eef_bc_grid import GridProfile
from .eef_bc_history import PERIOD_NS, SLOTS
from .eef_bc_policy import inputs, validate_cameras
from .eef_bc_data import NotReady, sha256
from .eef_action import check_increment


class StackObservations:
    """Receiver-clock alignment, original ingress guards, explicit disabled q7."""
    def __init__(self, contract, header_mode='strict'):
        if header_mode not in ('strict','receive-only-diagnostic'):
            raise ValueError('Unknown header mode')
        self.header_mode=header_mode
        self.profile = GridProfile(contract['wrist_camera'])
        if self.profile.CONTRACT != contract:
            raise ValueError('Unsupported checkpoint observation contract')
        self.contract = contract
        self.topics = {t:k for t,k in self.profile.TOPICS.items() if k != 'q'}
        self.counts = Counter(); self.accepted = Counter(); self.rejected = Counter()
        self.latest = {}; self.epoch = -1
        self.reset()

    def reset(self):
        self.buffer = self.profile.ObservationBuffer()
        self.history = OrderedDict()
        self.last_receive = None; self.last_reference = None
        self.epoch += 1
        self.latest.clear()

    def ingest(self, key, msg, receive_ns):
        if key not in self.topics.values():
            raise ValueError('Input not used by no-joint checkpoint: '+key)
        self.counts[key] += 1
        if self.last_receive is not None and receive_ns < self.last_receive:
            self.reset()
        self.last_receive = receive_ns
        metadata={}
        try:
            stamp,value = self.profile.decode(key,msg)
            if key == 'rgb' and (value.shape != (3,128,128) or value.dtype != np.uint8):
                raise ValueError('Expected uint8 external RGB')
            age = receive_ns-stamp
            metadata=dict(header_ns=stamp,header_age_ms=age/1e6)
            limit = self.contract['eef_max_age_ns'] if key=='eef' else self.contract['max_age_ns']
            if self.header_mode=='strict' and age < -self.contract['ingress_max_header_ahead_ns']:
                raise ValueError('header_ahead')
            if self.header_mode=='strict' and age > limit:
                raise ValueError('old_header')
            self.buffer.add(key,receive_ns,value)
        except (ValueError,AttributeError,TypeError,KeyError) as exc:
            self.buffer.data[key].clear()
            reason=str(exc)
            self.rejected[key+':'+reason] += 1
            self.latest[key]=dict(receive_ns=receive_ns,accepted=False,reason=reason,**metadata)
            return False
        self.accepted[key] += 1
        self.latest[key]=dict(receive_ns=receive_ns,header_ns=stamp,header_age_ms=age/1e6,accepted=True)
        return True

    def window(self, reference_ns):
        if self.last_reference is not None:
            if reference_ns <= self.last_reference:
                self.reset()
            elif (reference_ns-self.last_reference)%PERIOD_NS:
                raise ValueError('References must stay on the 100ms lattice')
        self.last_reference=reference_ns
        for t in list(self.history):
            if t < reference_ns-(SLOTS-1)*PERIOD_NS:del self.history[t]
        # Explicit no-joint placeholder, not a received or measured robot state.
        self.buffer.add('q',reference_ns,np.zeros(7,np.float32))
        status=dict(reference_ns=reference_ns,expires_ns=reference_ns+PERIOD_NS,
                    epoch=self.epoch,inferred=False,reason='missing_current',action=None,
                    joint_enabled=0,execution_allowed=False,header_mode=self.header_mode,
                    training_header_guards_enforced=self.header_mode=='strict')
        try:
            obs,stamps=self.buffer.at(reference_ns)
        except NotReady as exc:
            status['reason']=str(exc)
            return None,status
        validate_cameras({k:v[None] for k,v in obs.items()},self.contract)
        self.history[reference_ns]=obs
        template={k:np.zeros_like(v) for k,v in obs.items()}
        refs=[reference_ns-(SLOTS-1-i)*PERIOD_NS for i in range(SLOTS)]
        mask=np.array([t in self.history for t in refs],dtype=bool)
        data={k:np.stack([self.history.get(t,template)[k] for t in refs]) for k in obs}
        status.update(history_mask=mask.tolist(),camera_mask=obs['camera_mask'].astype(int).tolist(),
                      source_receive_ns={k:int(v) for k,v in stamps.items() if k!='q'},
                      source_receive_age_ms={k:(reference_ns-v)/1e6 for k,v in stamps.items() if k!='q'},
                      eef_xyz_xyzw=obs['state'][7:].tolist())
        return (data,mask),status


def infer_window(model,norm,window,device):
    data,mask=window
    if device.type=='cuda':torch.cuda.synchronize()
    started=time.perf_counter_ns()
    with torch.inference_mode():
        x=tuple(v.to(device)[None] for v in inputs(data,norm))
        pred=model.forward_windows(x,torch.as_tensor(mask,device=device)[None]).cpu().numpy()[0]
    action=pred*np.asarray(norm['delta_std'],np.float32).reshape(6)+np.asarray(norm['delta_mean'],np.float32).reshape(6)
    if device.type=='cuda':torch.cuda.synchronize()
    elapsed=(time.perf_counter_ns()-started)/1e6
    return action,elapsed


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--duration',type=float,default=60.,help='seconds of live observation after model loading')
    p.add_argument('--device',choices=('cuda','cpu'),default='cuda')
    p.add_argument('--header-mode',choices=('strict','receive-only-diagnostic'),default='strict',
                   help='diagnostic bypasses source-header age only; receive freshness/shape/frame checks remain')
    args=p.parse_args()
    if not np.isfinite(args.duration) or args.duration<=0:p.error('duration must be positive and finite')
    args.output.mkdir(parents=True,exist_ok=False)
    device=torch.device(args.device)
    if device.type=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no implicit fallback')
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.backends.cudnn.benchmark=False
    torch.use_deterministic_algorithms(True)
    model,norm,checkpoint=load_stack_policy(args.checkpoint,device)
    if checkpoint['config']['version']!=NO_JOINT_VERSION:raise ValueError('This live runner requires the no-joint checkpoint')
    runtime=StackObservations(model.contract,args.header_mode)
    manifest=dict(checkpoint=str(args.checkpoint.resolve()),checkpoint_sha256=sha256(args.checkpoint),
                  version=checkpoint['config']['version'],step=checkpoint['step'],device=str(device),
                  gpu=torch.cuda.get_device_name() if device.type=='cuda' else None,
                  domain=os.environ.get('ROS_DOMAIN_ID'),topics=runtime.topics,contract=model.contract,
                  joint_enabled=0,action_publishers=[],action_order=['dx','dy','dz','rx','ry','rz'],
                  action_units=['m','m','m','rad','rad','rad'],period_ns=PERIOD_NS,
                  deployment='file-only shadow; no robot commands; EEF/base/TCP alignment unresolved',
                  header_mode=args.header_mode,
                  timing='receiver ROS clock; source-header age guards per header_mode; no clock offset correction',
                  inference_timing='normalization + tensor transfer + forward + denormalization; excludes decode and transport')
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from geometry_msgs.msg import PoseStamped
    rclpy.init();node=rclpy.create_node('omi_stack_shadow',enable_rosout=False,start_parameter_services=False)
    lock=threading.Lock();stop=threading.Event();errors=[]
    def receive(key,msg):
        with lock:runtime.ingest(key,msg,node.get_clock().now().nanoseconds)
    for topic,key in runtime.topics.items():
        node.create_subscription(PoseStamped if key=='eef' else Image,topic,
            lambda msg,k=key:receive(k,msg),qos_profile_sensor_data)
    executor=SingleThreadedExecutor();executor.add_node(node)
    def spin():
        try:
            while not stop.is_set() and rclpy.ok():executor.spin_once(timeout_sec=.05)
        except Exception as exc:
            errors.append(repr(exc));stop.set()
    thread=threading.Thread(target=spin,daemon=True);thread.start()
    rows=[];next_reference=None;last_clock=None;saved=False;started=time.monotonic();last_print=started-5
    print(f'SHADOW ONLY: {manifest["version"]}, {device}, {args.header_mode}, no action publishers; output {args.output}',flush=True)
    try:
        with (args.output/'predictions.jsonl').open('w') as log:
            while time.monotonic()-started<args.duration and not stop.is_set() and rclpy.ok():
                now=node.get_clock().now().nanoseconds
                if last_clock is not None and now<last_clock:
                    with lock:runtime.reset()
                    next_reference=None
                last_clock=now
                if next_reference is None:next_reference=now
                if now<next_reference:
                    stop.wait(min(.01,(next_reference-now)/1e9));continue
                reference=next_reference+((now-next_reference)//PERIOD_NS)*PERIOD_NS
                next_reference=reference+PERIOD_NS
                begin=time.perf_counter_ns()
                with lock:
                    window,status=runtime.window(reference)
                    status['ingress_latest']={k:dict(v) for k,v in runtime.latest.items()}
                if window is not None:
                    action,elapsed=infer_window(model,norm,window,device)
                    finite=bool(np.isfinite(action).all())
                    status.update(inferred=True,finite=finite,inference_ms=elapsed,
                                  action=action.tolist() if finite else None,reason='ok' if finite else 'nonfinite_output')
                    try:check_increment(action,model.contract['max_translation_m'],model.contract['max_rotation_rad'])
                    except ValueError as exc:status.update(within_experimental_bounds=False,bounds_reason=str(exc))
                    else:status['within_experimental_bounds']=True
                    z=(window[0]['state'][-1,7:]-np.asarray(norm['state_mean'])[0,7:])/np.asarray(norm['state_std'])[0,7:]
                    status['eef_standardized_by_training_stats']=z.tolist()
                    status['eef_max_abs_z']=float(np.max(np.abs(z)))
                    if not saved:
                        np.savez_compressed(args.output/'first_window.npz',**window[0],history_mask=window[1],action=action)
                        saved=True
                finished=node.get_clock().now().nanoseconds
                status['step_wall_ms']=(time.perf_counter_ns()-begin)/1e6
                status['deadline_met']=reference<=finished<reference+PERIOD_NS
                status['reference_to_finish_ms']=(finished-reference)/1e6
                rows.append(status);log.write(json.dumps(status,allow_nan=False)+'\n');log.flush()
                (args.output/'status.tmp').write_text(json.dumps(status,indent=2)+'\n')
                (args.output/'status.tmp').replace(args.output/'status.json')
                if time.monotonic()-last_print>=5:
                    print(f"t={time.monotonic()-started:.1f}s inferred={sum(r['inferred'] for r in rows)}/{len(rows)} last={status['reason']} history={sum(status.get('history_mask',[]))}/10",flush=True)
                    last_print=time.monotonic()
    except KeyboardInterrupt:pass
    finally:
        stop.set();thread.join(timeout=2)
        executor.shutdown();node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        inferred=[r for r in rows if r['inferred']]
        def stats(values):
            return {k:float(v) for k,v in zip(('min','p50','p95','max'),np.percentile(values,[0,50,95,100]))} if values else None
        report=dict(duration_seconds=time.monotonic()-started,decisions=len(rows),inferences=len(inferred),
            finite_outputs=sum(r.get('finite',False) for r in inferred),
            within_experimental_bounds=sum(r.get('within_experimental_bounds',False) for r in inferred),
            deadline_met=sum(r['deadline_met'] for r in inferred),
            full_history_inferences=sum(all(r['history_mask']) for r in inferred),
            reasons=dict(Counter(r['reason'] for r in rows)),
            received=dict(runtime.counts),accepted=dict(runtime.accepted),rejected=dict(runtime.rejected),
            inference_ms=stats([r['inference_ms'] for r in inferred]),
            reference_to_finish_ms=stats([r['reference_to_finish_ms'] for r in inferred]),
            eef_max_abs_z=stats([r['eef_max_abs_z'] for r in inferred]),
            execution_allowed=False,action_publishers=[],worker_errors=errors,header_mode=args.header_mode)
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
    return 0 if inferred and not errors else 2


if __name__=='__main__':raise SystemExit(main())
