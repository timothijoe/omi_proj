import json,sys,zipfile,tempfile,hashlib,time
from pathlib import Path
from collections import Counter
import numpy as np
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from omi_hil_rl.training.bag_bc_data import open_bag, reader
from omi_hil_rl.real.ros_topics import decode_image_message
from omi_hil_rl.training.eef_action import pose
import argparse
parser=argparse.ArgumentParser(description="Read-only ROS bag inventory, timing, numeric checks and camera thumbnails")
parser.add_argument("source",type=Path)
parser.add_argument("output",type=Path)
args=parser.parse_args()
root=args.output;root.mkdir(parents=True,exist_ok=False)
src=args.source
reports=[]
for source in sorted(src.glob('*.zip')):
 out=root/(source.stem+'_audit.json')
 if out.exists():
  reports.append(json.loads(out.read_text()));continue
 print('AUDIT',source.name,flush=True)
 report={'source':str(source),'errors':[],'topics':{}}
 try:
  with tempfile.TemporaryDirectory(dir=root) as scratch:
   with open_bag(source,scratch) as (info,paths,provenance):
    report.update(provenance=provenance,duration_s=info['duration']['nanoseconds']/1e9,metadata_count=info['message_count'])
    expected={t['topic_metadata']['name']:t['message_count'] for t in info['topics_with_message_count']}
    stats={}; last={}; intervals={}; delays={}; hashes={}; eefs=[]; prev_rx=None
    for p in paths:
     rd=reader(p); classes={t.name:get_message(t.type) for t in rd.get_all_topics_and_types()}
     for t in rd.get_all_topics_and_types():
      stats.setdefault(t.name,dict(type=t.type,count=0,invalid=0,backward=0,duplicate_stamp=0,future_header=0,formats={}))
     while rd.has_next():
      topic,data,rx=rd.read_next(); st=stats[topic]; st['count']+=1
      if prev_rx is not None and rx<prev_rx: report['errors'].append('reception_backwards')
      prev_rx=rx
      try:
       m=deserialize_message(data,classes[topic])
       if hasattr(m,'header'):
        ns=m.header.stamp.sec*10**9+m.header.stamp.nanosec
        if ns<=0: raise ValueError('nonpositive header')
        if ns>rx:st['future_header']+=1
        if topic in last:
         dt=ns-last[topic]; st['backward']+=int(dt<0); st['duplicate_stamp']+=int(dt==0)
         intervals.setdefault(topic,[]).append(dt/1e6)
        last[topic]=ns; delays.setdefault(topic,[]).append((rx-ns)/1e6)
       if hasattr(m,'encoding'):
        a=decode_image_message(m)
        if not np.isfinite(a).all():raise ValueError('nonfinite image')
        fmt=f'{m.height}x{m.width}:{m.encoding}'
        st['formats'][fmt]=st['formats'].get(fmt,0)+1
        if 'color' in topic:
         h=hashlib.sha256(bytes(m.data)).hexdigest(); hashes.setdefault(topic,set()).add(h)
         if st['count'] in (1,60,120,240,480):
          from PIL import Image
          im=Image.fromarray(a); im.thumbnail((480,270)); im.save(root/f'{source.stem}_{"wrist" if "wrist" in topic else "external"}_{st["count"]}.jpg')
        if a.dtype.kind=='f':
         st['value_min']=min(st.get('value_min',float('inf')),float(a.min()));st['value_max']=max(st.get('value_max',float('-inf')),float(a.max()))
       if topic=='/tj/info/eef_left':
        xyz=m.pose.position;q=m.pose.orientation
        v=pose([xyz.x,xyz.y,xyz.z,q.x,q.y,q.z,q.w]);eefs.append(v)
        st.setdefault('frames',{})[m.header.frame_id]=st.setdefault('frames',{}).get(m.header.frame_id,0)+1
       if hasattr(m,'arm_positions'):
        a=np.asarray(m.arm_positions)
        if a.shape!=(14,) or not np.isfinite(a).all():raise ValueError('invalid joint feedback')
      except Exception as ex:
       st['invalid']+=1;st.setdefault('first_error',str(ex))
     del rd
    def dist(a):
     a=np.asarray(a);return dict(min=float(a.min()),p50=float(np.median(a)),p95=float(np.percentile(a,95)),max=float(a.max())) if len(a) else None
    for topic,st in stats.items():
     st['expected']=expected.get(topic,0);st['count_matches']=st['count']==st['expected']
     st['header_dt_ms']=dist(intervals.get(topic,[]));st['receive_delay_ms']=dist(delays.get(topic,[]))
     if topic in hashes:st['unique_image_payloads']=len(hashes[topic])
    report['topics']=stats;report['actual_count']=sum(s['count'] for s in stats.values())
    if eefs:
     a=np.array(eefs);report['eef_xyz_range_m']=(a[:,:3].max(0)-a[:,:3].min(0)).tolist()
 except Exception as ex: report['errors'].append(repr(ex))
 out.write_text(json.dumps(report,indent=2)+'\n');reports.append(report)
 print('DONE',source.name,report.get('duration_s'),report.get('actual_count'),report['errors'],flush=True)
(root/'audit.json').write_text(json.dumps(reports,indent=2)+'\n')
