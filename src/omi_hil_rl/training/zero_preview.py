"""Offline real-sensor bag preview with zero placeholder labels; never training demos."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.demo import save_npz
from omi_hil_rl.hil.exchange import atomic_json
from .eef_bc_grid import GridProfile
from .stack_shadow import StackObservations

VERSION = 'omi-real-observation-zero-preview-v1'
PERIOD = 100_000_000


def load_step(directory, index, manifest):
    if manifest['version'] != VERSION or not 0 <= index < manifest['count']:
        raise ValueError('invalid diagnostic preview index/version')
    with np.load(Path(directory)/f'{index:06d}.npz',allow_pickle=False) as archive:
        obs={k[13:]:archive[k].copy() for k in archive.files if k.startswith('observation__')}
        nxt={k[18:]:archive[k].copy() for k in archive.files if k.startswith('next_observation__')}
        action=archive['executed_action'].copy()
        physical=archive['action_m_rad'].copy()
        meta=json.loads(str(archive['metadata']))
    if action.shape!=(6,) or np.any(action) or np.any(physical) or meta['action_source']!='zero_placeholder':
        raise ValueError('preview must have explicit zero placeholder labels')
    if meta['next_observation_time_ns']-meta['observation_time_ns']!=PERIOD:
        raise ValueError('preview pair must be exactly 100ms apart')
    return obs,nxt,action,meta


def convert(bag, output):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    bag,output=Path(bag).resolve(),Path(output)
    output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'conversion_pending.json',{'source':str(bag)})
    profile=GridProfile('required')
    strict=StackObservations(profile.CONTRACT,'strict','raw')
    diagnostic=StackObservations(profile.CONTRACT,'receive-only-diagnostic','raw')
    reader=rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag),storage_id=''),rosbag2_py.ConverterOptions('',''))
    types={t.name:t.type for t in reader.get_all_topics_and_types()}
    relevant={topic:key for topic,key in diagnostic.topics.items() if topic in types}
    classes={topic:get_message(types[topic]) for topic in relevant}
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(relevant)))
    directory=output/'episodes'/'zero_preview';directory.mkdir(parents=True)
    counts=Counter();ages={};strict_windows=0;diag_windows=0;reasons=Counter()
    next_ref=None;previous=None;count=0;start=None;last=None;stamps=[]
    def sample(reference):
        nonlocal previous,count,strict_windows,diag_windows
        sw,ss=strict.window(reference)
        strict_windows+=int(sw is not None and sw[1].all())
        window,status=diagnostic.window(reference)
        if window is None or not window[1].all():
            reasons[status['reason'] if window is None else 'history_warmup']+=1
            previous=None;return
        diag_windows+=1
        data,mask=window;obs=dict(data,history_mask=mask.astype(np.uint8))
        if previous is not None and reference-previous[1]==PERIOD:
            current,stamp,audit=previous
            meta=dict(episode='zero_preview',step=count,observation_time_ns=stamp,next_observation_time_ns=reference,
                      action_source='zero_placeholder',command_status='NOT_SENT; diagnostic placeholder',
                      current_observation_audit=audit,command_audit={'next_observation_status':status},
                      header_mode='receive-only-diagnostic',training_allowed=False)
            arrays={'observation__'+k:v for k,v in current.items()}
            arrays.update({'next_observation__'+k:v for k,v in obs.items()})
            arrays.update(executed_action=np.zeros(6,np.float32),action_m_rad=np.zeros(6,np.float32),
                          metadata=np.asarray(json.dumps(meta)))
            save_npz(directory/f'{count:06d}.npz',arrays);count+=1;stamps.append(stamp)
        previous=(obs,reference,status)
    while reader.has_next():
        topic,payload,t=reader.read_next()
        if next_ref is None:start=t;next_ref=t
        while next_ref<t:
            sample(next_ref);next_ref+=PERIOD
        msg=deserialize_message(payload,classes[topic]);key=relevant[topic]
        strict.ingest(key,msg,t);diagnostic.ingest(key,msg,t)
        counts[topic]+=1
        stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        ages.setdefault(topic,[]).append((t-stamp)/1e6)
        last=t
    # Do not extrapolate a window after the last observed message.
    if last is not None and next_ref==last:sample(next_ref)
    config=HILConfig(transport='ros',wrist_camera='required')
    manifest=dict(version=VERSION,episode='zero_preview',count=count,keep=True,valid=True,
                  synthetic=False,training_allowed=False,operator_outcome='diagnostic_zero_labels',
                  contract=config.replay_contract(),raw_bag=str(bag),reward_available=False,
                  action_semantics='zero_placeholder_NOT_SENT',header_mode='receive-only-diagnostic')
    report=dict(version=VERSION,bag=str(bag),samples=count,strict_complete_windows=strict_windows,
                diagnostic_complete_windows=diag_windows,missing_windows=dict(reasons),
                strict_rejections=dict(strict.rejected),diagnostic_rejections=dict(diagnostic.rejected),
                observed_span_s=(last-start)/1e9 if last is not None else 0,
                action='all zero placeholders; not sent; not human labels',training_allowed=False,
                sample_spacing_ms=sorted(set(np.diff(stamps).astype(float)/1e6)) if len(stamps)>1 else [],
                topics={t:dict(count=counts[t],header_age_ms=dict(zip(('min','p50','p95','max'),
                      map(float,np.percentile(v,[0,50,95,100]))))) for t,v in ages.items()})
    atomic_json(output/'report.json',report)
    if count:
        atomic_json(directory/'demo.json',manifest)
        (output/'conversion_pending.json').unlink()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bag',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(json.dumps(convert(args.bag,args.output),indent=2))


if __name__=='__main__':main()
