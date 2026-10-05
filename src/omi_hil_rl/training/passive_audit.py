"""Read-only structural, timing and value audit for passive gamepad bags."""
import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3

import numpy as np

from .eef_bc_grid import GridProfile
from .stack_shadow import StackObservations
from omi_hil_rl.hil.exchange import atomic_json
from omi_hil_rl.real.ros_topics import wrench_value


def summary(values):
    if not len(values):return None
    return dict(zip(('min','p50','p95','max'),map(float,np.percentile(values,[0,50,95,100]))))


def audit(session, output):
    import rosbag2_py
    import yaml
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    session=Path(session).resolve();output=Path(output);output.mkdir(parents=True,exist_ok=False)
    bag=session/'raw';metadata=yaml.safe_load((bag/'metadata.yaml').read_text())['rosbag2_bagfile_information']
    config=json.loads((session/'session.json').read_text());command_topic=config['command_topic']
    integrity=[]
    for path in bag.glob('*.db3'):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            integrity.append(dict(file=path.name,result=db.execute('PRAGMA quick_check').fetchall()))
    reader=rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag),storage_id=''),rosbag2_py.ConverterOptions('',''))
    types={t.name:t.type for t in reader.get_all_topics_and_types()}
    classes={t:get_message(kind) for t,kind in types.items()}
    profile=GridProfile('required');inputs={t:k for t,k in profile.TOPICS.items() if k!='q'}
    strict=StackObservations(profile.CONTRACT,'strict');diag=StackObservations(profile.CONTRACT,'receive-only-diagnostic')
    counters={t:dict(times=[],headers=[],ages=[],errors=Counter(),shapes=Counter(),frames=Counter(),hashes=set(),low=None,high=None) for t in types}
    windows=Counter();next_ref=None;command_rows=[];all_count=0
    def window(t):
        for name,runtime in [('strict',strict),('receive_diagnostic',diag)]:
            value,status=runtime.window(t)
            if value is not None and value[1].all():windows[name+'_complete']+=1
            else:windows[name+':'+(status['reason'] if value is None else 'history_warmup')]+=1
    while reader.has_next():
        topic,payload,t=reader.read_next();all_count+=1;rec=counters[topic];rec['times'].append(t)
        if topic in inputs:
            if next_ref is None:next_ref=t
            while next_ref<t:window(next_ref);next_ref+=100_000_000
        try:
            msg=deserialize_message(payload,classes[topic])
            if hasattr(msg,'header'):
                stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
                rec['headers'].append(stamp);rec['ages'].append((t-stamp)/1e6);rec['frames'][msg.header.frame_id]+=1
            if topic in inputs:
                _,value=profile.decode(inputs[topic],msg)
                strict.ingest(inputs[topic],msg,t);diag.ingest(inputs[topic],msg,t)
            elif topic.endswith('/wrench'):value=wrench_value(msg)
            elif topic=='/tj/info/joint_feedback':
                value=np.r_[msg.positions,msg.velocities,msg.efforts].astype(np.float64)
                if value.shape!=(42,):raise ValueError('unexpected joint feedback shape')
            elif topic==command_topic:
                value=np.asarray(msg.data,np.float64)
                if value.shape!=(6,) or not np.isfinite(value).all():raise ValueError('invalid six-dimensional command')
                command_rows.append(dict(bag_receive_ns=t,wire_action=value.tolist(),
                                         labels=[d.label for d in msg.layout.dim],has_nonzero=bool(np.any(value))))
            else:continue
            if not np.isfinite(value).all():raise ValueError('nonfinite observation')
            rec['shapes'][str(value.shape)]+=1
            rec['low']=float(value.min()) if rec['low'] is None else min(rec['low'],float(value.min()))
            rec['high']=float(value.max()) if rec['high'] is None else max(rec['high'],float(value.max()))
            rec['hashes'].add(hashlib.sha256(value.tobytes()).hexdigest())
            if topic=='/tj/info/eef_left':
                rec.setdefault('quaternion_error',[]).append(abs(float(np.linalg.norm(value[3:]))-1.))
        except Exception as exc:rec['errors'][type(exc).__name__+':'+str(exc)]+=1
    duration=metadata['duration']['nanoseconds']/1e9
    topics={}
    for topic,r in counters.items():
        dt=np.diff(np.asarray(r['times'],np.int64))/1e6;hs=np.diff(np.asarray(r['headers'],np.int64))
        topics[topic]=dict(type=types[topic],count=len(r['times']),average_hz=len(r['times'])/duration,
            receive_gap_ms=summary(dt),receive_gaps_over_150ms=int(np.sum(dt>150)),
            header_age_ms=summary(r['ages']),header_backwards=int(np.sum(hs<0)),header_repeated=int(np.sum(hs==0)),
            decode_errors=dict(r['errors']),shapes=dict(r['shapes']),frames=dict(r['frames']),
            unique_values=len(r['hashes']),value_range=[r['low'],r['high']],
            quaternion_norm_error=summary(r.get('quaternion_error',[])))
    cmds=np.asarray([r['wire_action'] for r in command_rows],np.float64).reshape(-1,6)
    command_info=dict(topic=command_topic,count=len(cmds),nonzero=sum(r['has_nonzero'] for r in command_rows),
        with_id=sum(bool(r['labels']) for r in command_rows),
        max_abs_by_component=np.max(np.abs(cmds),axis=0).tolist() if len(cmds) else None,
        max_translation_wire_norm=float(np.max(np.linalg.norm(cmds[:,:3],axis=1))) if len(cmds) else None,
        units='raw wire; confirm publisher conversion and home mode',
        receipt_count=topics.get('/omi/action/receipt',{}).get('count',0))
    expected={r['topic_metadata']['name']:r['message_count'] for r in metadata['topics_with_message_count']}
    report=dict(session=str(session),duration_s=duration,size_mib=sum(p.stat().st_size for p in bag.glob('*'))/2**20,
        message_type_sources={t:inspect.getfile(c) for t,c in classes.items()},sqlite_integrity=integrity,total_messages=all_count,metadata_counts_match=all(topics[t]['count']==n for t,n in expected.items()),
        topics=topics,commands=command_info,windows=dict(windows),strict_rejections=dict(strict.rejected),
        diagnostic_rejections=dict(diag.rejected),required_missing=[t for t in inputs if not topics.get(t,{}).get('count')],
        outcome='not present in passive bag; operator annotation required')
    atomic_json(output/'audit.json',report)
    with (output/'commands.jsonl').open('w') as f:
        for row in command_rows:f.write(json.dumps(row)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sessions',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    reports=[]
    for session in a.sessions:
        r=audit(session,a.output/session.name);reports.append(r)
        print(json.dumps(dict(bag=session.name,seconds=r['duration_s'],commands=r['commands'],windows=r['windows']),ensure_ascii=False),flush=True)
    atomic_json(a.output/'summary.json',reports)


if __name__=='__main__':main()
