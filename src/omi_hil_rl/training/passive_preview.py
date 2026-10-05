"""Strict sensor-window review paired with raw wire commands from passive bags.

Diagnostic export only: recorder timestamps do not prove command execution or
that the historical sender used the currently configured conversion mode.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .eef_bc_grid import GridProfile
from .sensor_alignment import AuditedObservations, read_sensor_metadata, prefer_record_topic, add_wrench_alignment
from .demo_wrench import read_wrenches, align_history, MAX_AGE_NS
from omi_hil_rl.hil.demo import save_npz
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.exchange import atomic_json

VERSION='omi-passive-wire-preview-v1'
PERIOD=100_000_000


def commands_between(commands, start, end):
    times=np.asarray([r['bag_receive_ns'] for r in commands],np.int64)
    return commands[int(np.searchsorted(times,start,'left')):int(np.searchsorted(times,end,'left'))]


def load_step(directory,index,manifest):
    if manifest['version']!=VERSION or not 0<=index<manifest['count']:raise ValueError('invalid passive preview index/version')
    with np.load(Path(directory)/f'{index:06d}.npz',allow_pickle=False) as archive:
        obs={k[13:]:archive[k].copy() for k in archive.files if k.startswith('observation__')}
        nxt={k[18:]:archive[k].copy() for k in archive.files if k.startswith('next_observation__')}
        wire=archive['recorded_wire_action'].copy();meta=json.loads(str(archive['metadata']))
    now,after=meta['observation_time_ns'],meta['next_observation_time_ns']
    rx=meta['command_audit']['command_receive_ns']
    if wire.shape!=(6,) or not np.isfinite(wire).all() or not now<=rx<after or after-now!=PERIOD:
        raise ValueError('invalid passive wire/timing pair')
    if not np.array_equal(wire,meta['command_audit']['wire_action']):raise ValueError('wire metadata mismatch')
    return obs,nxt,wire,meta


def convert(session,output,max_tactile_skew_ms=None):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    session,output=Path(session).resolve(),Path(output)
    settings=json.loads((session/'session.json').read_text());topic=settings['command_topic'];bag=session/'raw'
    def reader_for(topics):
        reader=rosbag2_py.SequentialReader()
        reader.open(rosbag2_py.StorageOptions(uri=str(bag),storage_id=''),rosbag2_py.ConverterOptions('',''))
        reader.set_filter(rosbag2_py.StorageFilter(topics=topics))
        return reader
    commands=[];reader=reader_for([topic]);types={t.name:t.type for t in reader.get_all_topics_and_types()}
    if types.get(topic)!='std_msgs/msg/Float64MultiArray':raise ValueError('missing or incompatible command topic')
    command_class=get_message(types[topic])
    while reader.has_next():
        _,payload,t=reader.read_next();msg=deserialize_message(payload,command_class);wire=np.asarray(msg.data,np.float64)
        if wire.shape!=(6,) or not np.isfinite(wire).all():raise ValueError('malformed command')
        commands.append(dict(bag_receive_ns=t,wire_action=wire.tolist(),labels=[d.label for d in msg.layout.dim]))
    if not commands:raise ValueError('no recorded commands')
    commands.sort(key=lambda r:r['bag_receive_ns']);del reader
    wrenches=read_wrenches(bag)
    runtime=AuditedObservations(GridProfile('required').CONTRACT,'strict','raw',
        provenance=read_sensor_metadata(bag), max_tactile_skew_ms=max_tactile_skew_ms)
    prefer_record_topic(runtime, types)
    reader=reader_for(list(runtime.topics));classes={t:get_message(types[t]) for t in runtime.topics if t in types}
    output.mkdir(parents=True,exist_ok=False);atomic_json(output/'conversion_pending.json',dict(session=str(session)))
    directory=output/'episodes'/session.name;directory.mkdir(parents=True)
    count=0;previous=None;next_ref=None;counts=Counter();selected=[];last=None
    def sample(reference):
        nonlocal previous,count
        window,status=runtime.window(reference)
        if window is None or not window[1].all():
            counts[status['reason'] if window is None else 'history_warmup']+=1;previous=None;return
        data,mask=window;obs=dict(data,history_mask=mask.astype(np.uint8))
        aligned,frames=align_history(wrenches,reference);obs.update(aligned)
        add_wrench_alignment(status, aligned, runtime.provenance, reference)
        if previous is not None and reference-previous[1]==PERIOD:
            current,stamp,audit,old_frames=previous
            candidates=commands_between(commands,stamp,reference)
            if len(candidates)!=1:counts['no_command' if not candidates else 'multiple_commands']+=1
            elif status['source_receive_ns']['eef']<=candidates[0]['bag_receive_ns']:
                counts['no_eef_received_after_command']+=1
            else:
                command=candidates[0]
                meta=dict(episode=session.name,step=count,observation_time_ns=stamp,next_observation_time_ns=reference,
                    action_source='recorded_wire_unverified',command_status='RECORDED_WIRE; no command receipt',
                    header_mode='strict',training_allowed=False,current_observation_audit=audit,
                    observation_wrench_frame_ids=old_frames,next_observation_wrench_frame_ids=frames,
                    command_audit=dict(command_topic=topic,command_receive_ns=command['bag_receive_ns'],
                        wire_action=command['wire_action'],wire_labels=command['labels'],next_observation_status=status),
                    alignment='one raw command received in [obs reference,next reference); recorder-clock pairing only')
                arrays={'observation__'+k:v for k,v in current.items()}
                arrays.update({'next_observation__'+k:v for k,v in obs.items()})
                arrays.update(recorded_wire_action=np.asarray(command['wire_action'],np.float64),metadata=np.asarray(json.dumps(meta)))
                save_npz(directory/f'{count:06d}.npz',arrays)
                selected.append(dict(step=count,command_receive_ns=command['bag_receive_ns'],wire_action=command['wire_action']))
                count+=1
        previous=(obs,reference,status,frames)
    while reader.has_next():
        tpc,payload,t=reader.read_next()
        if next_ref is None:next_ref=t
        while next_ref<t:sample(next_ref);next_ref+=PERIOD
        msg=deserialize_message(payload,classes[tpc]);runtime.ingest(runtime.topics[tpc],msg,t);last=t
    if last is not None and next_ref==last:sample(next_ref)
    config=HILConfig(transport='ros',wrist_camera='required')
    report=dict(version=VERSION,source_bag=str(bag),samples=count,command_messages=len(commands),
                excluded=dict(counts),strict_rejections=dict(runtime.rejected),training_allowed=False,
                alignment='strict 10-frame observations; exact one received command per 100ms pair; post-command received EEF',
                max_tactile_host_header_skew_ms=max_tactile_skew_ms,
                limitations=['command receive time is not source send time','no sender mode or command ID/receipt',
                             'no success/failure or episode annotations','wire coordinates not converted into policy coordinates'],
                selected=selected)
    atomic_json(output/'report.json',report)
    if count:
        manifest=dict(version=VERSION,episode=session.name,count=count,keep=True,valid=True,synthetic=False,
            training_allowed=False,operator_outcome='unlabelled_real_commands',raw_bag=str(bag),reward_available=False,
            action_semantics='raw_wire_not_execution_confirmed',header_mode='strict',contract=config.replay_contract(),
            display_action='raw_wire',wire_display_scale=np.maximum(np.max(np.abs([r['wire_action'] for r in commands]),axis=0),1e-9).tolist(),
            auxiliary_observations=dict(wrench=dict(shape=[10,2,6],max_receive_age_ns=MAX_AGE_NS,
                                                  units='raw SDK values; N/Nm not verified')))
        atomic_json(directory/'demo.json',manifest);(output/'conversion_pending.json').unlink()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-tactile-skew-ms',type=float,help='optional host-header skew bound; not device exposure skew')
    args=p.parse_args();r=convert(args.session,args.output,args.max_tactile_skew_ms)
    print(json.dumps({k:v for k,v in r.items() if k!='selected'},indent=2))


if __name__=='__main__':main()
