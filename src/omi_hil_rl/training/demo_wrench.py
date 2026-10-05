"""Add causal, masked dual-finger wrench histories to diagnostic demo datasets."""
import argparse
import json
from pathlib import Path

import numpy as np

from omi_hil_rl.hil.demo import save_npz
from omi_hil_rl.hil.exchange import atomic_json
from .zero_preview import VERSION, PERIOD

TOPICS = {f'/omi/tactile_grid24x16/{side}/wrench': side for side in 'ab'}
MAX_AGE_NS = 250_000_000


def read_wrenches(bag):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from geometry_msgs.msg import WrenchStamped
    from omi_hil_rl.real.ros_topics import wrench_value
    reader=rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(Path(bag).resolve()),storage_id=''),rosbag2_py.ConverterOptions('',''))
    types={t.name:t.type for t in reader.get_all_topics_and_types()}
    for t in TOPICS:
        if t in types and types[t]!='geometry_msgs/msg/WrenchStamped':
            raise ValueError('unexpected wrench type: '+t)
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(TOPICS)))
    records={side:[] for side in 'ab'}
    while reader.has_next():
        topic,payload,receive=reader.read_next()
        msg=deserialize_message(payload,WrenchStamped)
        header=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        try:values=wrench_value(msg)
        except ValueError:values=np.full(6,np.nan,np.float32)
        records[TOPICS[topic]].append((receive,header,values,msg.header.frame_id))
    return {side:sorted(rows,key=lambda r:r[0]) for side,rows in records.items()}


def align_history(records, reference, max_age_ns=MAX_AGE_NS):
    """Last received sample at or before each history time; never look ahead."""
    values=np.zeros((10,2,6),np.float32)
    mask=np.zeros((10,2),np.uint8)
    receive=np.zeros((10,2),np.int64);header=np.zeros((10,2),np.int64)
    frames=[['',''] for _ in range(10)]
    for side_index,side in enumerate('ab'):
        rows=records.get(side,[]);times=np.asarray([r[0] for r in rows],np.int64)
        for slot in range(10):
            t=reference-(9-slot)*PERIOD
            index=int(np.searchsorted(times,t,side='right'))-1
            if index<0:continue
            rx,stamp,v,frame=rows[index]
            receive[slot,side_index]=rx;header[slot,side_index]=stamp;frames[slot][side_index]=frame
            if 0<=t-rx<=max_age_ns and np.asarray(v).shape==(6,) and np.isfinite(v).all():
                values[slot,side_index]=v;mask[slot,side_index]=1
    return dict(wrench=values,wrench_mask=mask,wrench_receive_ns=receive,wrench_header_ns=header),frames


def enrich(dataset, bag, output):
    dataset,bag,output=Path(dataset),Path(bag).resolve(),Path(output)
    manifests=sorted(dataset.glob('episodes/*/demo.json'))
    if not manifests or (dataset/'conversion_pending.json').exists():raise ValueError('no complete input dataset')
    if any(json.loads(p.read_text())['version']!=VERSION for p in manifests):
        raise ValueError('this enrichment is for diagnostic previews; policy input contracts are unchanged')
    records=read_wrenches(bag)
    output.mkdir(parents=True,exist_ok=False)
    atomic_json(output/'conversion_pending.json',dict(source=str(dataset.resolve())))
    specification=dict(version='dual-wrench-receive-history-v1',shape=[10,2,6],side_order=['a','b'],
        components=['Fx','Fy','Fz','Tx','Ty','Tz'],units='raw SDK values; N/Nm not verified',
        alignment='latest bag receive time <= history slot time; original header/frame_id preserved',
        max_receive_age_ns=MAX_AGE_NS,missing='wrench_mask=0; zero storage is not a measurement',
        source_bag=str(bag),training_input=False)
    counts=np.zeros(2,np.int64);samples=0
    for path in manifests:
        manifest=json.loads(path.read_text());target=output/'episodes'/path.parent.name;target.mkdir(parents=True)
        for index in range(manifest['count']):
            with np.load(path.parent/f'{index:06d}.npz',allow_pickle=False) as archive:
                arrays={key:archive[key].copy() for key in archive.files}
            metadata=json.loads(str(arrays['metadata']))
            for prefix,clock in [('observation','observation_time_ns'),('next_observation','next_observation_time_ns')]:
                aligned,frames=align_history(records,metadata[clock])
                arrays.update({prefix+'__'+key:value for key,value in aligned.items()})
                metadata[prefix+'_wrench_frame_ids']=frames
                if prefix=='observation':counts+=aligned['wrench_mask'][-1]
            arrays['metadata']=np.asarray(json.dumps(metadata))
            save_npz(target/f'{index:06d}.npz',arrays);samples+=1
        manifest['auxiliary_observations']={'wrench':specification}
        atomic_json(target/'demo.json',manifest)
    report=dict(samples=samples,source_dataset=str(dataset.resolve()),wrench=specification,
                source_counts={side:len(records[side]) for side in 'ab'},
                valid_current_frames=dict(zip('ab',map(int,counts))),training_allowed=False)
    atomic_json(output/'wrench_report.json',report)
    if (dataset/'report.json').exists():
        original=json.loads((dataset/'report.json').read_text());original['wrench_enrichment']=report
        atomic_json(output/'report.json',original)
    (output/'conversion_pending.json').unlink()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True);p.add_argument('--bag',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(json.dumps(enrich(args.dataset,args.bag,args.output),indent=2))


if __name__=='__main__':main()
