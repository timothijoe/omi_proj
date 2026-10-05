"""Record every received tactile wrench and display live or saved history in RViz."""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

NS = '/omi/live_wrench'
COLORS = ('#ff7777', '#72dfaa', '#79baff')
COMPONENTS = ('Fx', 'Fy', 'Fz', 'Tx', 'Ty', 'Tz')


def positive(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('Expected a positive finite value')
    return value


class Monitor:
    def __init__(self, window=15., stale=.5):
        self.window, self.stale = window, stale
        self.history = {s: deque() for s in 'ab'}
        self.latest = {}
        self.counts = dict(a=0, b=0)
        self.invalid = dict(a=0, b=0)

    def ingest(self, side, message, receive_ros_ns, elapsed):
        w = message.wrench
        values = [w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z]
        valid = all(math.isfinite(v) for v in values)
        stamp = message.header.stamp
        header_ns = stamp.sec * 10**9 + stamp.nanosec
        row = dict(schema_version=1, side=side, elapsed_s=elapsed,
                   receive_ros_ns=receive_ros_ns, header_ros_ns=header_ns,
                   frame_id=message.header.frame_id, valid=valid,
                   values=[v if math.isfinite(v) else None for v in values],
                   error=None if valid else 'nonfinite_wrench')
        self.counts[side] += 1
        self.invalid[side] += int(not valid)
        self.latest[side] = row
        self.history[side].append(row)
        self.trim(elapsed)
        return row

    def trim(self, elapsed):
        for rows in self.history.values():
            while rows and rows[0]['elapsed_s'] < elapsed-self.window:
                rows.popleft()

    def status(self, elapsed):
        self.trim(elapsed)
        result = {}
        for side in 'ab':
            row = self.latest.get(side)
            age = None if row is None else elapsed-row['elapsed_s']
            state = 'WAITING' if row is None else 'STALE' if age > self.stale else 'LIVE' if row['valid'] else 'INVALID'
            times = [r['elapsed_s'] for r in self.history[side] if elapsed-r['elapsed_s'] <= 2]
            hz = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
            result[side] = dict(state=state, received=self.counts[side], invalid=self.invalid[side], hz=hz,
                                receive_age_ms=None if age is None else age*1000,
                                header_age_at_receive_ms=None if row is None else (row['receive_ros_ns']-row['header_ros_ns'])/1e6,
                                values=row['values'] if state=='LIVE' else None,
                                frame_id=None if row is None else row['frame_id'])
        return result


def font(size):
    try:
        return ImageFont.truetype('DejaVuSansMono.ttf', size)
    except OSError:
        return ImageFont.load_default()


def axis_bounds(values, min_span):
    """Stable zero-centred range, growing only in powers of two."""
    if not math.isfinite(min_span) or min_span <= 0:
        raise ValueError('Minimum axis span must be positive and finite')
    half = min_span/2
    peak = max((abs(v) for v in values), default=0.)
    while peak > half:
        half *= 2
    return -half, half


def plot(draw, box, points, start, end, indices, gap=.5, envelope=False, min_span=4.):
    x0, y0, x1, y1 = box
    values = [v for p in points if p[1] is not None for v in (p[1]+p[2] if envelope else p[1])]
    lo, hi = axis_bounds(values, min_span)
    xy = lambda t,v: (x0+(t-start)/max(end-start,1e-9)*(x1-x0), y1-(v-lo)/(hi-lo)*(y1-y0))
    for i in range(5):
        v = lo+(hi-lo)*i/4
        y = xy(start,v)[1]
        draw.line((x0,y,x1,y),fill='#384351')
        draw.text((x0-86,y-7),f'{v:+.3g}',font=font(13),fill='#bac6d3')
    draw.rectangle(box,outline='#657181')
    for j, index in enumerate(indices):
        previous = None
        for point in points:
            if envelope:
                t, lower, upper = point
                draw.line((*xy(t,lower[j]),*xy(t,upper[j])),fill=COLORS[j],width=2)
            else:
                t, vals = point
                if vals is None:
                    previous = None
                    continue
                if previous and t-previous[0] <= gap:
                    draw.line((*xy(previous[0],previous[1][j]),*xy(t,vals[j])),fill=COLORS[j],width=2)
                else:
                    x,y=xy(t,vals[j]);draw.ellipse((x-1,y-1,x+1,y+1),fill=COLORS[j])
                previous = (t,vals)
        draw.text((x0+j*145,y0-25),COMPONENTS[index],font=font(17),fill=COLORS[j])
    for i in range(5):
        t = start+(end-start)*i/4
        draw.text((xy(t,lo)[0]-18,y1+8),f'{t:.1f}s',font=font(13),fill='#bac6d3')


def render(histories, status, start, end, title, envelope=False, stale=.5,
           force_min_span=4., torque_min_span=1.):
    canvas = Image.new('RGB',(1440,880),'#121923')
    draw = ImageDraw.Draw(canvas)
    draw.text((20,12),title,font=font(22),fill='white')
    draw.text((20,43),'Raw SDK values; units/axes NOT calibrated. Wrench freshness and field synchronization NOT verified.',font=font(15),fill='#f2c36e')
    draw.text((20,66),f'Axis minimum: Force +/-{force_min_span/2:g}, Torque +/-{torque_min_span/2:g}; zero-centered; expands in 2x steps.',font=font(15),fill='#bac6d3')
    for col, side in enumerate('ab'):
        x=col*720
        r=status[side]
        heading=f"Finger {side.upper()} | {r['state']} | received {r['received']}" if envelope else f"Finger {side.upper()} | {r['state']} | {r.get('hz',0):.1f} Hz | received {r['received']}"
        draw.text((x+20,102),heading,font=font(19),fill='#72dfaa' if r['state']=='LIVE' else '#ffbb77')
        age=r.get('receive_age_ms')
        detail=f"Recorded range: {start:.2f} to {end:.2f}s | invalid: {r.get('invalid',0)}" if envelope else f"RX age: {'--' if age is None else f'{age:.0f} ms'} | frame: {r.get('frame_id') or '?'} | invalid: {r.get('invalid',0)}"
        draw.text((x+20,131),detail,font=font(15),fill='#bac6d3')
        for group in range(2):
            y=172+group*340
            indices=tuple(range(group*3,group*3+3))
            vals=r.get('values')
            label='Force' if group==0 else 'Torque'
            text=' / '.join(f'{COMPONENTS[i]}={vals[i]:+.5f}' for i in indices) if vals is not None else 'Recorded min/max envelope' if envelope else 'No current valid value'
            draw.text((x+20,y),label+' | '+text,font=font(16),fill='white')
            if vals is not None:
                norm=math.sqrt(sum(vals[i]**2 for i in indices))
                draw.text((x+20,y+24),f'Vector magnitude: {norm:.5f} (uncalibrated SDK units)',font=font(14),fill='#bac6d3')
            if envelope:
                points=[(t,lo[group*3:group*3+3],hi[group*3:group*3+3]) for t,lo,hi in histories[side]]
            else:
                points=[(row['elapsed_s'],row['values'][group*3:group*3+3] if row['valid'] else None) for row in histories[side]]
            plot(draw,(x+108,y+88,x+693,y+270),points,start,end,indices,gap=stale,envelope=envelope,
                 min_span=force_min_span if group==0 else torque_min_span)
    draw.text((20,855),'Full history: peak-preserving min/max bins; exact samples in samples.jsonl.' if envelope else 'Every received sample is recorded to disk. Curves stop at gaps/invalid data. Close RViz or Ctrl+C to finish.',font=font(15),fill='#f2c36e')
    return canvas


def review_session(folder, force_min_span=None, torque_min_span=None):
    """Two streaming passes; fixed-memory min/max bins retain brief peaks."""
    folder=Path(folder)
    manifest_path=folder/'manifest.json'
    settings=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if force_min_span is None:force_min_span=settings.get('force_min_span',4.)
    if torque_min_span is None:torque_min_span=settings.get('torque_min_span',1.)
    start,end=None,None
    counts=dict(a=0,b=0);invalid=dict(a=0,b=0)
    with (folder/'samples.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line);t=row['elapsed_s'];side=row['side']
            start=t if start is None else min(start,t);end=t if end is None else max(end,t)
            counts[side]+=1;invalid[side]+=int(not row['valid'])
    start=0. if start is None else start;end=max(start+1e-6,end or 0.)
    bins={s:{} for s in 'ab'}
    with (folder/'samples.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line)
            if not row['valid']:continue
            i=min(579,int((row['elapsed_s']-start)/(end-start)*580))
            values=np.array(row['values']);target=bins[row['side']]
            if i not in target:target[i]=[values.copy(),values.copy()]
            else:target[i]=[np.minimum(target[i][0],values),np.maximum(target[i][1],values)]
    history={s:[(start+(i+.5)/580*(end-start),lo.tolist(),hi.tolist()) for i,(lo,hi) in sorted(bins[s].items())] for s in 'ab'}
    status={s:dict(state='RECORDED',received=counts[s],invalid=invalid[s],values=None) for s in 'ab'}
    destination=folder/'history.png'
    render(history,status,start,end,'RECORDED TACTILE WRENCH | '+folder.name,envelope=True,
           force_min_span=force_min_span,torque_min_span=torque_min_span).save(destination)
    return destination


def run_node(args):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import qos_profile_sensor_data
    from geometry_msgs.msg import WrenchStamped
    from sensor_msgs.msg import Image as ImageMsg
    from std_msgs.msg import String
    from rclpy.clock import Clock, ClockType
    rclpy.init()
    node=rclpy.create_node('omi_wrench_recorder',enable_rosout=False,start_parameter_services=False)
    monitor=Monitor(args.window,args.stale)
    started=time.monotonic();output=args.output
    samples=(output/'samples.jsonl').open('x');metadata=(output/'metadata.jsonl').open('x')
    pub=node.create_publisher(ImageMsg,NS+'/dashboard',1)
    latest_meta={}
    def receive(side,msg):
        row=monitor.ingest(side,msg,node.get_clock().now().nanoseconds,time.monotonic()-started)
        samples.write(json.dumps(row,allow_nan=False)+'\n')
    def receive_metadata(side,msg):
        try:
            value=json.loads(msg.data)
            row=dict(side=side,elapsed_s=time.monotonic()-started,receive_ros_ns=node.get_clock().now().nanoseconds,metadata=value)
            text=json.dumps(row,allow_nan=False)
        except (ValueError,TypeError):return
        metadata.write(text+'\n');latest_meta[side]=value
    for side,topic in (('a',args.topic_a),('b',args.topic_b)):
        node.create_subscription(WrenchStamped,topic,lambda m,s=side:receive(s,m),qos_profile_sensor_data)
        node.create_subscription(String,topic.rsplit('/',1)[0]+'/metadata',lambda m,s=side:receive_metadata(s,m),qos_profile_sensor_data)
    def tick():
        elapsed=time.monotonic()-started
        status=monitor.status(elapsed)
        image=render(monitor.history,status,max(0,elapsed-args.window),max(elapsed,.001),f'LIVE TACTILE WRENCH | domain {args.domain} | last {args.window:g}s',stale=args.stale,
                     force_min_span=args.force_min_span,torque_min_span=args.torque_min_span)
        msg=ImageMsg();msg.header.stamp=node.get_clock().now().to_msg();msg.header.frame_id='wrench_dashboard'
        msg.height,msg.width=880,1440;msg.encoding='rgb8';msg.step=1440*3;msg.data=np.asarray(image).tobytes()
        pub.publish(msg)
        image.save(output/'dashboard.tmp',format='PNG');(output/'dashboard.tmp').replace(output/'dashboard.png')
        report=dict(elapsed_s=elapsed,topics=status,metadata=latest_meta,recording='all received messages; not a lossless publisher audit')
        (output/'status.tmp').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');(output/'status.tmp').replace(output/'status.json')
        samples.flush();metadata.flush()
    node.create_timer(1/args.hz,tick,clock=Clock(clock_type=ClockType.STEADY_TIME))
    try:
        tick()
        while rclpy.ok():rclpy.spin_once(node,timeout_sec=.1)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        samples.close();metadata.close()
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        report=dict(duration_s=time.monotonic()-started,received=monitor.counts,invalid=monitor.invalid)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Saved full history: '+str(review_session(output)),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domain',type=int,default=int(os.environ.get('ROS_DOMAIN_ID','13')))
    p.add_argument('--topic-a',default='/omi/tactile_grid24x16/a/wrench')
    p.add_argument('--topic-b',default='/omi/tactile_grid24x16/b/wrench')
    p.add_argument('--window',type=positive,default=15.,help='visible rolling history seconds; disk recording retains all samples')
    p.add_argument('--stale',type=positive,default=.5,help='seconds without a message before STALE')
    p.add_argument('--hz',type=positive,default=5.,help='display refresh; recording follows every received message')
    p.add_argument('--force-min-span',type=positive,help='minimum full force axis span; default 4 = [-2,2]')
    p.add_argument('--torque-min-span',type=positive,help='minimum full torque axis span; default 1 = [-0.5,0.5]')
    p.add_argument('--duration',type=positive)
    p.add_argument('--output',type=Path,help='new session directory; never overwrite a recording')
    p.add_argument('--no-rviz',action='store_true')
    p.add_argument('--review-session',type=Path,help='rebuild saved full-history PNG without ROS')
    p.add_argument('--node',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.review_session:
        print(review_session(args.review_session,args.force_min_span,args.torque_min_span));return 0
    if args.force_min_span is None:args.force_min_span=4.
    if args.torque_min_span is None:args.torque_min_span=1.
    if not 0<=args.domain<=232:p.error('domain must be 0..232')
    if args.hz>10:p.error('display refresh must be <=10 Hz')
    if args.topic_a==args.topic_b:p.error('A and B topics must differ')
    if args.node:return run_node(args)
    root=Path(__file__).resolve().parents[3]
    if args.output:
        args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    else:
        runtime=root/'local/wrench_live';runtime.mkdir(parents=True,exist_ok=True)
        args.output=Path(tempfile.mkdtemp(prefix='session-',dir=runtime))
    manifest=dict(schema_version=1,started_utc_ns=time.time_ns(),domain=args.domain,topic_a=args.topic_a,topic_b=args.topic_b,
                  component_order=COMPONENTS,units='uncalibrated SDK values; not confirmed N or Nm',
                  timestamps='header and host receive ROS ns; elapsed steady seconds; NOT exposure synchronization',
                  recording='every received message, including invalid events; finite values unchanged; no baseline subtraction',
                  nonfinite='null component plus valid=false; not a zero measurement',visible_window_s=args.window,
                  stale_s=args.stale,display_hz=args.hz,output_publishers=[NS+'/dashboard'],
                  force_min_span=args.force_min_span,torque_min_span=args.torque_min_span,
                  axis_scale='zero-centred minimum span, doubled only when data exceeds range')
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    env=dict(os.environ,ROS_DOMAIN_ID=str(args.domain))
    commands=[[sys.executable,'-m','omi_hil_rl.real.wrench_live','--node','--output',str(args.output),
               '--domain',str(args.domain),'--topic-a',args.topic_a,'--topic-b',args.topic_b,
               '--window',str(args.window),'--stale',str(args.stale),'--hz',str(args.hz),
               '--force-min-span',str(args.force_min_span),'--torque-min-span',str(args.torque_min_span)]]
    if not args.no_rviz:commands.append(['rviz2','-d',str(root/'scripts/wrench_live.rviz')])
    print(f'Wrench recording: {args.output}\nImage topic: {NS}/dashboard; no robot commands.',flush=True)
    from omi_sensors.cli import supervise
    return supervise(commands,env,args.duration)


if __name__=='__main__':sys.exit(main())
