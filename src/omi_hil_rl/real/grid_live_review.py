"""Live read-only grid observation dashboard and RViz launcher; no control publishers."""
from __future__ import annotations
import argparse
from collections import deque
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from . import grid_recorded_review as grid

NS = '/omi/live_grid'
TOPICS = dict(grid.TOPICS)
TOPICS.update({f'/omi/tactile/{s}/raw': f'{s}_raw' for s in 'ab'})
REQUIRED = {'camera', 'wrist_roi', 'eef'} | {f'{s}_{k}' for s in 'ab' for k in ('deformation','shear','depth')}
MODEL_NS = NS + '/model'


def model_sample(monitor, report, key):
    """Visualization may inspect clock-skewed data, but never stale/invalid data."""
    item = monitor.latest.get(key)
    if item is None or report[key]['state'] == 'BAD_DATA':
        return None
    age = report[key]['receive_age_ms']
    if age is None or not 0 <= age <= 250:
        return None
    if key == 'eef' and item['frame'] != 'base_link':
        return None
    return item['value']


class CorrectedModelView:
    """Original replay conventions, isolated from the robot's TF/control graph."""
    def __init__(self, node, hz):
        from sensor_msgs.msg import JointState
        from visualization_msgs.msg import MarkerArray
        self.node, self.hz = node, hz
        import xml.etree.ElementTree as ET
        path = Path(os.environ['OMI_PROJECT_ROOT'])/'local/models/omi_marvin_stand_axis_corrected_v1/urdf/omi_marvin_stand_axis_corrected_v1.urdf'
        robot = ET.parse(path).getroot()
        self.left_chain = [robot.find(f"joint[@name='left_joint{i}']") for i in range(1,8)]
        self.joints = node.create_publisher(JointState, MODEL_NS+'/joint_states', 2)
        self.markers = node.create_publisher(MarkerArray, NS+'/model_markers', 2)

    def publish(self, monitor, report):
        from sensor_msgs.msg import JointState
        from visualization_msgs.msg import Marker, MarkerArray
        from geometry_msgs.msg import Point
        from scipy.spatial.transform import Rotation
        from .robot_replay_3d import JOINTS
        joints = model_sample(monitor, report, 'joints')
        eef = model_sample(monitor, report, 'eef')
        if joints is not None:
            msg = JointState()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.name, msg.position = JOINTS, joints.tolist()
            self.joints.publish(msg)
        array = MarkerArray()
        clear = Marker(); clear.action = Marker.DELETEALL
        array.markers.append(clear)
        def marker(ident, kind, frame):
            m = Marker()
            m.header.frame_id = frame
            m.ns, m.id, m.type = 'live_model_review', ident, kind
            m.pose.orientation.w = 1.
            m.color.r = m.color.g = m.color.a = 1.
            ttl = int(max(1., 2.5/self.hz)*1e9)
            m.lifetime.sec, m.lifetime.nanosec = divmod(ttl, 10**9)
            array.markers.append(m)
            return m
        def axes(offset, frame, position, rotation, length):
            for i in range(3):
                m = marker(offset+i, Marker.ARROW, frame)
                m.scale.x, m.scale.y, m.scale.z = .005, .012, .02
                m.color.r, m.color.g, m.color.b = [float(i == j) for j in range(3)]
                m.points = [Point(x=float(v[0]), y=float(v[1]), z=float(v[2]))
                            for v in (position, position+length*rotation[:, i])]
        if joints is not None:
            axes(0, 'omi_replay_left_link7', np.zeros(3), np.eye(3), .06)
            m = marker(3, Marker.TEXT_VIEW_FACING, 'omi_replay_left_link7')
            m.pose.position.z = .09; m.scale.z = .025
            m.text = 'URDF L7 origin (NOT TCP)'
        if eef is not None:
            axes(4, 'omi_replay_robot_base', eef[:3], Rotation.from_quat(eef[3:]).as_matrix(), .12)
            m = marker(7, Marker.TEXT_VIEW_FACING, 'omi_replay_robot_base')
            m.pose.position = Point(x=float(eef[0]), y=float(eef[1]), z=float(eef[2]+.1))
            m.scale.z = .025; m.text = 'ROS EEF: '+report['eef']['state']
        if joints is not None and eef is not None:
            transform = left_l7_transform(self.left_chain,joints[:7])
            start, end = transform[:3,3], eef[:3]
            frame = 'omi_replay_robot_base'
            for ident,position,color in ((9,start,(0.,1.,1.)),(10,end,(1.,0.,1.))):
                m = marker(ident,Marker.SPHERE,frame)
                m.pose.position = Point(x=float(position[0]),y=float(position[1]),z=float(position[2]))
                m.scale.x = m.scale.y = m.scale.z = .025
                m.color.r,m.color.g,m.color.b = color
            m = marker(11,Marker.LINE_LIST,frame)
            m.scale.x = .005
            m.color.r,m.color.g,m.color.b = 1.,.8,0.
            m.points = [Point(x=float(v[0]),y=float(v[1]),z=float(v[2])) for v in (start,end)]
            m = marker(12,Marker.TEXT_VIEW_FACING,frame)
            mid=(start+end)/2
            m.pose.position = Point(x=float(mid[0]),y=float(mid[1]),z=float(mid[2]+.16))
            m.scale.z = .027
            angle=Rotation.from_matrix(transform[:3,:3].T@Rotation.from_quat(eef[3:]).as_matrix()).magnitude()*180/np.pi
            gap=abs(monitor.latest['joints']['stamp']-monitor.latest['eef']['stamp'])/1e6
            m.text=(f'L7 -> EEF: {np.linalg.norm(end-start)*100:.1f} cm | axes: {angle:.1f} deg\n'
                    f'Latest samples, dt={gap:.0f} ms | NOT calibrated TCP error')
        m = marker(8, Marker.TEXT_VIEW_FACING, 'omi_replay_world')
        m.pose.position.z = 1.65; m.scale.z = .028
        m.text = ('Original corrected Stand | DISPLAY ONLY\n'
                  'Assume base_link = model root; no fitted TCP\n'
                  'joint_feedback: '+report['joints']['state']+' (original radians convention)\n'
                  + ('Robot pose received' if joints is not None else 'NO FRESH JOINTS: model absent or FROZEN')
                  +' | EEF: '+report['eef']['state'])
        self.markers.publish(array)


def left_l7_transform(chain, positions):
    """FK in the archived model root, with its already-corrected joint axes."""
    from scipy.spatial.transform import Rotation
    transform = np.eye(4)
    for joint,position in zip(chain,positions):
        origin = joint.find('origin')
        fixed = np.eye(4)
        fixed[:3,3] = np.fromstring(origin.get('xyz','0 0 0'),sep=' ')
        fixed[:3,:3] = Rotation.from_euler('xyz',np.fromstring(origin.get('rpy','0 0 0'),sep=' ')).as_matrix()
        motion = np.eye(4)
        axis = np.fromstring(joint.find('axis').get('xyz'),sep=' ')
        motion[:3,:3] = Rotation.from_rotvec(axis/np.linalg.norm(axis)*position).as_matrix()
        transform = transform@fixed@motion
    return transform


class Monitor:
    def __init__(self):
        self.latest = {}
        self.times = {k: deque(maxlen=150) for k in TOPICS.values()}
        self.errors = {}
        self.counts = {k: 0 for k in TOPICS.values()}
        self.publishers = {k: 0 for k in TOPICS.values()}
        self.types = {}

    def receive(self, key, message, received_ns, monotonic_ns):
        self.counts[key] += 1
        self.times[key].append(monotonic_ns)
        try:
            if key == 'joints':
                # Live firmware uses positions; historical bags use arm_positions.
                from .recorded_observation import source_stamp
                value = np.asarray(message.positions, dtype=float)
                if value.shape != (14,) or not np.isfinite(value).all():
                    raise ValueError('Expected fourteen finite live joint positions')
                item = dict(stamp=source_stamp(message), frame=message.header.frame_id, value=value)
            else:
                item = grid.decode(key, message)
            if key == 'camera' and (item['value'].ndim != 3 or item['value'].shape[2] != 3):
                raise ValueError('Expected RGB camera image')
            if key.endswith('_raw') and item['value'].ndim not in (2,3):
                raise ValueError('Expected raw image')
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            self.latest.pop(key, None)
            self.errors[key] = str(exc)
            return
        item.update(receive_ns=received_ns, monotonic_ns=monotonic_ns)
        self.latest[key] = item
        self.errors.pop(key, None)

    def report(self, now_ns, monotonic_ns):
        result = {}
        for topic, key in TOPICS.items():
            item = self.latest.get(key)
            times = [t for t in self.times[key] if monotonic_ns-t <= 3_000_000_000]
            hz = (len(times)-1)*1e9/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
            rx_age = (monotonic_ns-item['monotonic_ns'])/1e6 if item else None
            age = (now_ns-item['stamp'])/1e6 if item else None
            limit = 50. if key=='eef' else 250.
            if key in self.errors: state='BAD_DATA'
            elif item is None: state='WAITING' if self.publishers[key] else 'NO_PUBLISHER'
            elif rx_age > limit: state='STALE'
            elif age < -100: state='CLOCK_AHEAD'
            elif age > limit: state='OLD_HEADER'
            elif key=='eef' and item['frame']!='base_link': state='FRAME_CHECK'
            else: state='LIVE'
            result[key] = dict(topic=topic,state=state,required=key in REQUIRED,publishers=self.publishers[key],
                received=self.counts[key],hz=hz,receive_age_ms=rx_age,header_age_ms=age,
                frame_id=item['frame'] if item else None,error=self.errors.get(key),
                discovered_types=self.types.get(topic,[]))
        return result


def render(monitor, report, now_ns, elapsed, domain):
    # Hide invalid/old images, instead of showing an old frame as apparently live.
    valid = {k:v for k,v in monitor.latest.items() if report[k]['state']=='LIVE'}
    old = grid.render(valid, now_ns, elapsed, f'LIVE domain{domain}')
    canvas = Image.new('RGB',(1536,1540),(18,22,28));canvas.paste(old,(0,0))
    draw=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('DejaVuSansMono.ttf',16)
    except OSError:font=ImageFont.load_default()
    draw.rectangle((0,0,1535,53),fill=(18,22,28))
    draw.text((10,4),f'LIVE ROS domain {domain} | read-only | required views: RGB + wrist + tactile + EEF | no joints needed',font=font,fill='white')
    draw.text((10,27),'Independent latest samples, NOT synchronized policy input. Header age includes clock offset. No commands.',font=font,fill='#f1c46b')
    draw.rectangle((768,58,1535,79),fill=(18,22,28))
    draw.text((780,58),'Wrist LIVE ROI128 (enlarged only; no second crop)',font=font,fill='white')
    # Optional raw panels occupy the lower-right cells of the recorded grid layout.
    for i,s in enumerate('ab'):
        x=(i+2)*384;draw.rectangle((x,706,x+383,1029),fill=(18,22,28))
        draw.text((x+5,712),f'{s.upper()} raw (optional)',font=font,fill='white')
        item=valid.get(s+'_raw')
        if item:
            im=Image.fromarray(item['value']);im.thumbnail((374,275));canvas.paste(im,(x+5,750))
        else:draw.text((x+5,748),report[s+'_raw']['state'],font=font,fill='#f1c46b')
    draw.rectangle((0,1030,1535,1539),fill=(18,22,28))
    eef=monitor.latest.get('eef')
    text='EEF '+report['eef']['state']+' xyz / xyzw: '+('WAITING' if not eef else ' '.join(f'{v:+.5f}' for v in eef['value']))
    draw.text((10,1034),text,font=font,fill='white')
    draw.text((10,1056),'EEF frame: '+(eef['frame'] if eef else '?')+' | 3D model mode: '+getattr(monitor,'model_mode','none')+'; see 3D assumptions. TCP/base unverified.',font=font,fill='#f1c46b')
    draw.text((10,1084),'Topic                                                     State         Hz     RX age   Header age   Pub   Role',font=font,fill='white')
    for row,(key,r) in enumerate(report.items()):
        fmt=lambda v:'     --' if v is None else f'{v:7.0f}'
        line=f"{r['topic']:<57} {r['state']:<12} {r['hz']:5.1f} {fmt(r['receive_age_ms'])}ms {fmt(r['header_age_ms'])}ms {r['publishers']:3d}   {'REQ' if r['required'] else 'optional'}"
        draw.text((10,1110+row*24),line,font=font,fill='#8aefae' if r['state']=='LIVE' else '#ffb36b')
    return canvas


def run_node(args):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data, QoSProfile
    from rclpy.executors import ExternalShutdownException
    from sensor_msgs.msg import Image as ImageMsg
    from geometry_msgs.msg import PoseStamped, WrenchStamped
    from std_msgs.msg import String, Header
    from .tactile_live import image_message
    rclpy.init();node=rclpy.create_node('omi_live_grid_monitor');monitor=Monitor()
    monitor.model_mode = args.model_mode
    model_view = CorrectedModelView(node,args.hz) if args.model_mode == 'corrected' else None
    try:
        from marvin_msgs.msg import Jointfeedback
    except ImportError:
        Jointfeedback=None
        node.get_logger().warning('marvin_msgs unavailable: optional joints display disabled')
    pubs=[node.create_publisher(ImageMsg,NS+'/dashboard',QoSProfile(depth=1)),
          node.create_publisher(String,NS+'/status',10)]
    for topic,key in TOPICS.items():
        cls=Jointfeedback if key=='joints' else PoseStamped if key=='eef' else WrenchStamped if key.endswith('_force') else ImageMsg
        if cls is None:continue
        node.create_subscription(cls,topic,lambda msg,k=key:monitor.receive(k,msg,node.get_clock().now().nanoseconds,time.monotonic_ns()),qos_profile_sensor_data)
    started=time.monotonic();last_graph=0.;last_clock=None
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    def tick():
        nonlocal last_graph,last_clock
        now=node.get_clock().now().nanoseconds
        if last_clock is not None and now<last_clock:
            monitor.latest.clear();monitor.errors.clear()
        last_clock=now
        if time.monotonic()-last_graph>=1:
            monitor.types=dict(node.get_topic_names_and_types())
            for topic,key in TOPICS.items():monitor.publishers[key]=node.count_publishers(topic)
            last_graph=time.monotonic()
        report=monitor.report(now,time.monotonic_ns())
        if model_view:model_view.publish(monitor,report)
        image=render(monitor,report,now,time.monotonic()-started,args.domain)
        header=Header();header.stamp=node.get_clock().now().to_msg();header.frame_id='live_dashboard'
        pubs[0].publish(image_message(np.asarray(image),header,'rgb8'))
        status=dict(domain=args.domain,elapsed_seconds=time.monotonic()-started,topics=report,model_mode=args.model_mode,
                    required_topics_live=all(report[k]['state']=='LIVE' for k in REQUIRED),
                    note='Viewer only; not policy preprocessing or calibration acceptance')
        pubs[1].publish(String(data=json.dumps(status,allow_nan=False)))
        # Atomic replace allows read-only status checks while running.
        (output/'status.tmp').write_text(json.dumps(status,indent=2)+'\n');(output/'status.tmp').replace(output/'status.json')
        image.save(output/'dashboard.tmp',format='PNG');(output/'dashboard.tmp').replace(output/'dashboard.png')
    node.create_timer(1/args.hz,tick)
    node.get_logger().info(f'Live read-only dashboard: {NS}/dashboard; required missing inputs stay visible in status')
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    except RuntimeError:
        # Jazzy may surface a take_message conversion error during context shutdown.
        if rclpy.ok():raise
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domain',type=int,default=13)
    p.add_argument('--hz',type=grid.positive,default=2.,help='dashboard refresh, default2Hz; sensor subscriptions independent')
    p.add_argument('--fixed-frame',help='RViz fixed frame; default depends on model mode')
    p.add_argument('--model-mode',choices=('corrected','existing','none'),default='corrected',help='default: original corrected Stand review model')
    p.add_argument('--no-rviz',action='store_true')
    p.add_argument('--robot-model',action='store_true',help='enable existing RobotModel; requires matching local mesh package and complete live TF')
    p.add_argument('--duration',type=grid.positive)
    p.add_argument('--output',type=Path,help='new session output directory; defaults to local/grid_live_review/session-*')
    p.add_argument('--node',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.robot_model:args.model_mode='existing'
    if args.fixed_frame is None:args.fixed_frame='omi_replay_world' if args.model_mode=='corrected' else 'base_link'
    if not 0<=args.domain<=232:p.error('domain must be 0..232')
    if args.hz>10:p.error('dashboard hz must be <=10')
    root=Path(os.environ['OMI_PROJECT_ROOT'])
    if args.node:return run_node(args)
    runtime=root/'local/grid_live_review';runtime.mkdir(parents=True,exist_ok=True)
    with (runtime/f'domain-{args.domain}.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:p.error('live viewer already running in this domain')
        if args.output:
            args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
        else:args.output=Path(tempfile.mkdtemp(prefix='session-',dir=runtime))
        import yaml
        config=yaml.safe_load((root/'scripts/grid_live_observation.rviz').read_text())
        config['Visualization Manager']['Global Options']['Fixed Frame']=args.fixed_frame
        config['Visualization Manager']['Displays'][1]['Enabled']=args.model_mode!='none'
        config['Visualization Manager']['Displays'][1]['Value']=args.model_mode!='none'
        config['Visualization Manager']['Views']['Current']['Target Frame']=args.fixed_frame
        model = None
        if args.model_mode=='corrected':
            from .wrist_recorded_review import prepare_model
            model=prepare_model(root/'local/models/omi_marvin_stand_axis_corrected_v1',args.output,root/'scripts/grid_live_observation.rviz')
            displays=config['Visualization Manager']['Displays']
            displays[1]['Name']='Original corrected Stand (review assumptions)'
            displays[1]['Description Topic']['Value']=MODEL_NS+'/robot_description'
            displays[2]={'Class':'rviz_default_plugins/MarkerArray','Name':'Live EEF and L7 comparison',
                'Enabled':True,'Value':True,'Topic':{'Value':NS+'/model_markers','Depth':2,
                'Reliability Policy':'Reliable','Durability Policy':'Volatile','History Policy':'Keep Last'}}
        config_path=args.output/'live.rviz';config_path.write_text(yaml.safe_dump(config))
        env=dict(os.environ,ROS_DOMAIN_ID=str(args.domain),ROS_LOCALHOST_ONLY='0',ROS_AUTOMATIC_DISCOVERY_RANGE='SUBNET',
                 FASTRTPS_DEFAULT_PROFILES_FILE=str(root/'ros2/omi_sensors/config/live_dashboard_network.xml'))
        command=[sys.executable,'-m','omi_hil_rl.real.grid_live_review','--node','--domain',str(args.domain),'--hz',str(args.hz),'--output',str(args.output),'--model-mode',args.model_mode]
        commands=[command]
        tf_remaps=['--ros-args','-r','/tf:='+MODEL_NS+'/tf','-r','/tf_static:='+MODEL_NS+'/tf_static']
        if model:
            commands.append(['ros2','run','robot_state_publisher','robot_state_publisher',
                *tf_remaps,'-r','__ns:='+MODEL_NS,'--params-file',str(model/'publisher.yaml')])
        if not args.no_rviz:commands.append(['rviz2','-d',str(config_path)]+(tf_remaps if model else []))
        print(f'Live viewer domain{args.domain}; session {args.output}; close RViz or Ctrl+C to stop. No control publishers.',flush=True)
        from omi_sensors.cli import supervise
        return supervise(commands,env,args.duration)


if __name__=='__main__':sys.exit(main())
