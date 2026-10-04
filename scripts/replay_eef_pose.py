#!/usr/bin/env python3
"""Convert a PoseStamped MCAP to base-frame deltas, then replay like axis_test.

Standalone: Python 3.10+, numpy; ROS is imported only by prepare/send.
No automatic move to start. Rotation contract: base-frame rotvec, LEFT multiply.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np

CONTRACT = 'eef-recorded-base-rotvec-mm-deg-v1'


def quat(q):
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(n - 1) > 1e-3:
        raise ValueError('Invalid xyzw quaternion')
    return q / n


def mul(a, b):
    return np.r_[a[3]*b[:3]+b[3]*a[:3]+np.cross(a[:3], b[:3]),
                 a[3]*b[3]-np.dot(a[:3], b[:3])]


def delta(a, b):
    q = quat(mul(quat(b[3:]), np.r_[-quat(a[3:])[:3], quat(a[3:])[3]]))
    if q[3] < 0:
        q = -q
    n = np.linalg.norm(q[:3])
    r = 2*q[:3] if n < 1e-12 else q[:3]*(2*np.arctan2(n, q[3])/n)
    return np.r_[b[:3]-a[:3], r]


def integrate(p, d):
    angle = np.linalg.norm(d[3:])
    q = np.r_[d[3:]*(.5 if angle < 1e-12 else np.sin(angle/2)/angle), np.cos(angle/2)]
    return np.r_[p[:3]+d[:3], quat(mul(q, p[3:]))]


def interpolate(t, poses, at):
    """Linear position and shortest-arc quaternion SLERP, clamped endpoints."""
    at = np.clip(np.asarray(at), t[0], t[-1])
    hi = np.clip(np.searchsorted(t, at, side='right'), 1, len(t)-1)
    lo = hi-1
    u = (at-t[lo])/(t[hi]-t[lo])
    a, b = poses[lo, 3:].copy(), poses[hi, 3:].copy()
    dot = np.sum(a*b, axis=1)
    b[dot < 0] *= -1
    dot = np.clip(abs(dot), 0, 1)
    angle = np.arccos(dot)
    near = dot > .9995
    q = (1-u[:, None])*a + u[:, None]*b
    idx = ~near
    q[idx] = (np.sin((1-u[idx])*angle[idx])[:, None]*a[idx]
              + np.sin(u[idx]*angle[idx])[:, None]*b[idx])/np.sin(angle[idx])[:, None]
    q /= np.linalg.norm(q, axis=1)[:, None]
    return np.c_[(1-u[:, None])*poses[lo, :3]+u[:, None]*poses[hi, :3], q]


def pose_msg(m):
    p, q = m.pose.position, m.pose.orientation
    result = np.array([p.x, p.y, p.z, q.x, q.y, q.z, q.w])
    if not np.isfinite(result).all():
        raise ValueError('Nonfinite pose')
    result[3:] = quat(result[3:])
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def prepare(args):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from geometry_msgs.msg import PoseStamped
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(args.bag), storage_id='mcap'),
                rosbag2_py.ConverterOptions('cdr', 'cdr'))
    types = {x.name: x.type for x in reader.get_all_topics_and_types()}
    if types.get(args.pose_topic) != 'geometry_msgs/msg/PoseStamped':
        raise ValueError('Expected PoseStamped topic')
    records, stamps, frames = [], [], set()
    while reader.has_next():
        topic, raw, receive = reader.read_next()
        if topic != args.pose_topic:
            continue
        msg = deserialize_message(raw, PoseStamped)
        stamps.append(msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
                      if args.clock == 'header' else receive)
        records.append(pose_msg(msg)); frames.add(msg.header.frame_id)
    if len(records) < 2 or len(frames) != 1 or not next(iter(frames)):
        raise ValueError('Need at least two poses in one nonempty frame')
    stamps = np.asarray(stamps, dtype=np.int64)
    if (np.diff(stamps) <= 0).any():
        raise ValueError('Timestamps must be strictly increasing; choose receive clock only after inspection')
    t = (stamps-stamps[0])/1e9
    if np.diff(t).max() > args.max_gap:
        raise ValueError('Source gap exceeds --max-gap; do not bridge unknown motion')
    poses = np.array(records)
    end = t[-1] if args.end is None else args.end
    if not 0 <= args.start < end <= t[-1] or not 0 < args.speed <= 1:
        raise ValueError('Require 0 <= start < end <= duration and 0 < speed <= 1')
    grid = np.arange(int(np.ceil((end-args.start)*args.rate/args.speed))+1)/args.rate
    source_grid = np.minimum(args.start+grid*args.speed, end)
    sampled = interpolate(t, poses, source_grid)
    actions = np.array([delta(a, b) for a, b in zip(sampled[:-1], sampled[1:])])
    wire = actions*np.array([1000]*3+[180/np.pi]*3)
    reconstructed = [sampled[0]]
    for action in actions:
        reconstructed.append(integrate(reconstructed[-1], action))
    errors = np.array([delta(a, b) for a, b in zip(sampled, reconstructed)])
    selected = (t >= args.start) & (t <= end)
    approximation = interpolate(grid, sampled, (t[selected]-args.start)/args.speed)
    loss = np.array([delta(a, b) for a, b in zip(poses[selected], approximation)])
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output/'trajectory.npz', source_t=t, source_pose=poses,
                        t=grid, source_grid=source_grid, pose=sampled, action_m_rad=actions, action_mm_deg=wire)
    with (args.output/'actions.csv').open('w') as f:
        w = csv.writer(f); w.writerow(['index', 'send_s', 'target_s', 'dx_mm','dy_mm','dz_mm','rx_deg','ry_deg','rz_deg'])
        for i, action in enumerate(wire):
            w.writerow([i, grid[i], grid[i+1], *action])
    manifest = dict(contract=CONTRACT, source=str(args.bag.resolve()), pose_topic=args.pose_topic,
                    frame=next(iter(frames)), source_position_unit='m (PoseStamped SI assumption)',
                    rotation='base rotvec, R_next=Exp(dr) R_current; receiver assumption, not verified',
                    clock=args.clock, rate=args.rate, speed=args.speed, source_start_s=args.start, source_end_s=float(end), source_samples=len(t), actions=len(actions),
                    source_duration_s=float(t[-1]), replay_duration_s=float(grid[-1]),
                    final_interval='endpoint reached during final full period; tail padded < one period',
                    initial_pose_m_xyzw=sampled[0].tolist(), final_pose_m_xyzw=sampled[-1].tolist(),
                    max_step_translation_mm=float(np.linalg.norm(wire[:,:3], axis=1).max()),
                    max_step_rotation_deg=float(np.linalg.norm(wire[:,3:], axis=1).max()),
                    reconstruction_max_position_m=float(np.linalg.norm(errors[:,:3], axis=1).max()),
                    reconstruction_max_rotation_rad=float(np.linalg.norm(errors[:,3:], axis=1).max()),
                    resampling_max_position_mm=float(np.linalg.norm(loss[:,:3], axis=1).max()*1000),
                    resampling_max_rotation_deg=float(np.rad2deg(np.linalg.norm(loss[:,3:], axis=1).max())),
                    trajectory_sha256=hashlib.sha256((args.output/'trajectory.npz').read_bytes()).hexdigest(),
                    hardware_executed=False)
    write_json(args.output/'manifest.json', manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def load_dataset(path):
    m = json.loads((path/'manifest.json').read_text())
    raw = (path/'trajectory.npz').read_bytes()
    if m['contract'] != CONTRACT or hashlib.sha256(raw).hexdigest() != m['trajectory_sha256']:
        raise ValueError('Dataset contract/hash mismatch')
    with np.load(path/'trajectory.npz', allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    a = d['action_mm_deg']
    if a.ndim != 2 or a.shape[1] != 6 or not np.isfinite(a).all() or len(a) != len(d['pose'])-1:
        raise ValueError('Invalid actions')
    return m, d


def compare(dataset, log):
    m, d = load_dataset(dataset)
    rows = [json.loads(s) for s in log.read_text().splitlines()]
    starts = [r for r in rows if r['kind'] == 'start']
    if not starts:
        raise ValueError('No replay start in log')
    if starts[0]['trajectory_sha256'] != m['trajectory_sha256']:
        raise ValueError('Log belongs to another trajectory')
    start = starts[0]['origin_s']
    feedback = [r for r in rows if r['kind'] == 'feedback' and 0 <= r['monotonic_s']-start <= d['t'][-1]]
    sent = [r for r in rows if r['kind'] == 'sent']
    if not feedback:
        raise ValueError('No feedback during trajectory')
    t = np.array([r['monotonic_s']-start for r in feedback])
    actual = np.array([r['pose'] for r in feedback])
    expected = interpolate(d['t'], d['pose'], t)
    err = np.array([delta(a, b) for a, b in zip(expected, actual)])
    pos = np.linalg.norm(err[:,:3], axis=1)*1000
    rot = np.rad2deg(np.linalg.norm(err[:,3:], axis=1))
    report = dict(feedback_samples=len(t), sent_actions=len(sent), planned_actions=len(d['action_mm_deg']),
                  completed=any(r['kind']=='complete' for r in rows),
                  comparison='absolute trajectory vs nominal time, using local feedback receive time; includes latency',
                  coverage_s=[float(t[0]), float(t[-1])],
                  position_rmse_mm=float(np.sqrt(np.mean(pos**2))), position_max_mm=float(pos.max()),
                  rotation_rmse_deg=float(np.sqrt(np.mean(rot**2))), rotation_max_deg=float(rot.max()))
    final_feedback = [r for r in rows if r['kind'] == 'feedback' and r['monotonic_s'] >= start]
    if report['completed'] and final_feedback:
        final_error = delta(d['pose'][-1], np.asarray(final_feedback[-1]['pose']))
        report['after_settle_endpoint_position_mm'] = float(np.linalg.norm(final_error[:3])*1000)
        report['after_settle_endpoint_rotation_deg'] = float(np.rad2deg(np.linalg.norm(final_error[3:])))
    write_json(log.with_suffix('.comparison.json'), report)
    with log.with_suffix('.comparison.csv').open('w') as f:
        w = csv.writer(f); w.writerow(['elapsed_s','position_error_mm','rotation_error_deg',
                                      'actual_x_m','actual_y_m','actual_z_m','reference_x_m','reference_y_m','reference_z_m'])
        w.writerows([[tt, pp, rr, *aa[:3], *ee[:3]] for tt,pp,rr,aa,ee in zip(t,pos,rot,actual,expected)])
    print(json.dumps(report, indent=2))


def send(args):
    m, d = load_dataset(args.dataset)
    if not args.confirm_controller_contract:
        raise ValueError('Explicit --confirm-controller-contract required: selected arm, base axes/TCP, m feedback, mm/deg base rotvec increments')
    a = d['action_mm_deg']
    if np.linalg.norm(a[:,:3], axis=1).max() > args.max_step_mm or np.linalg.norm(a[:,3:], axis=1).max() > args.max_step_deg:
        raise ValueError('Trajectory exceeds requested per-step limits; inspect manifest, no silent clipping')
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from std_msgs.msg import Float64MultiArray
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    rclpy.init()
    node = rclpy.create_node('eef_recorded_trajectory_replay')
    pub = node.create_publisher(Float64MultiArray, args.action_topic, 1)
    latest = [None]
    args.log.parent.mkdir(parents=True, exist_ok=True)
    stream = args.log.open('x')
    def record(kind, **kwargs):
        stream.write(json.dumps(dict(kind=kind, monotonic_s=time.monotonic(), **kwargs), allow_nan=False)+'\n')
        stream.flush()
    def feedback(msg):
        try:
            p = pose_msg(msg)
            if msg.header.frame_id != m['frame']:
                raise ValueError('Feedback frame differs from reference')
            stamp = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
            age = (node.get_clock().now().nanoseconds-stamp)/1e9
            if not -.1 <= age <= args.feedback_timeout:
                raise ValueError('Feedback header stale or clock mismatch')
            if latest[0] is not None and stamp <= latest[0][2]:
                raise ValueError('Feedback timestamp stopped or moved backwards')
            latest[0] = (time.monotonic(), p, stamp)
            record('feedback', pose=p.tolist(), header_ns=stamp)
        except ValueError as exc:
            latest[0] = None
            record('feedback_invalid', reason=str(exc))
    sub = node.create_subscription(PoseStamped, args.feedback_topic or m['pose_topic'], feedback,
          QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE))
    def spin_until(deadline):
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(.01, max(0., deadline-time.monotonic())))
    def state():
        if latest[0] is None or time.monotonic()-latest[0][0] > args.feedback_timeout:
            raise RuntimeError('No fresh valid pose feedback; publication stopped')
        return latest[0][1]
    try:
        print('Reference start [m, xyzw]:', m['initial_pose_m_xyzw'])
        print('Topic:', args.action_topic, 'feedback:', args.feedback_topic or m['pose_topic'])
        print('Actions:',len(a),'rate:',m['rate'],'Hz; no automatic move to start.')
        print('Stopping publication is NOT a controller stop. Use the device stop if needed.')
        input('确认右/左臂选择、坐标/TCP、接收端单位和旋转语义，手动到达起点后，按回车检查并发送：')
        spin_until(time.monotonic()+2.)
        p = state(); error = delta(d['pose'][0], p)
        if np.linalg.norm(error[:3])*1000 > args.start_mm or np.rad2deg(np.linalg.norm(error[3:])) > args.start_deg:
            raise RuntimeError('Start mismatch: %.3f mm / %.3f deg' %
                               (np.linalg.norm(error[:3])*1000,np.rad2deg(np.linalg.norm(error[3:]))))
        if pub.get_subscription_count() != 1:
            raise RuntimeError('Expected exactly one command subscriber; check controller/topic')
        period = 1/m['rate']; start = time.monotonic()
        record('start', origin_s=start, dataset=str(args.dataset.resolve()), trajectory_sha256=m['trajectory_sha256'],
               initial_feedback=p.tolist(), action_topic=args.action_topic)
        for i, action in enumerate(a):
            deadline = start+i*period
            spin_until(deadline)
            if time.monotonic()-deadline > args.max_lateness:
                raise RuntimeError('Missed command deadline; no catch-up burst')
            state()
            if pub.get_subscription_count() != 1:
                raise RuntimeError('Command subscriber count changed')
            msg = Float64MultiArray(); msg.data = action.tolist()  # empty layout, mm/deg, like axis_test
            pub.publish(msg)
            record('sent', index=i, target_s=float(d['t'][i+1]), action_mm_deg=action.tolist())
        spin_until(start+len(a)*period+args.settle)
        state()
        record('complete')
    except (Exception, KeyboardInterrupt) as exc:
        record('aborted', reason=str(exc))
        raise
    finally:
        stream.close(); node.destroy_node(); rclpy.shutdown()
        # Partial runs remain auditable; comparison does not claim completion.
        try:
            compare(args.dataset, args.log)
        except ValueError as exc:
            print('Comparison unavailable:', exc)


def positive(v):
    n = float(v)
    if not np.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('prepare', help='Offline only: read bag and export actions')
    q.add_argument('bag', type=Path); q.add_argument('--output', type=Path, required=True)
    q.add_argument('--pose-topic', default='/tj/info/eef_right')
    q.add_argument('--clock', choices=['header','receive'], default='header')
    q.add_argument('--rate', type=positive, default=10.)
    q.add_argument('--max-gap', type=positive, default=.05)
    q.add_argument('--speed', type=positive, default=1., help='Source-time / replay-time, (0,1]; rate stays fixed')
    q.add_argument('--start', type=float, default=0., help='Source offset seconds')
    q.add_argument('--end', type=positive, help='Source end seconds, default entire recording')
    q = sub.add_parser('send', help='Publish to controller and record live PoseStamped feedback')
    q.add_argument('dataset', type=Path); q.add_argument('--log', type=Path, required=True)
    q.add_argument('--action-topic', default='/omi/action_test/decision')
    q.add_argument('--feedback-topic')
    q.add_argument('--confirm-controller-contract', action='store_true')
    q.add_argument('--max-step-mm', type=positive, default=1.)
    q.add_argument('--max-step-deg', type=positive, default=.2)
    q.add_argument('--start-mm', type=positive, default=2.)
    q.add_argument('--start-deg', type=positive, default=1.)
    q.add_argument('--feedback-timeout', type=positive, default=.25)
    q.add_argument('--max-lateness', type=positive, default=.02)
    q.add_argument('--settle', type=positive, default=1.)
    q = sub.add_parser('compare', help='Recompute trajectory errors from send log')
    q.add_argument('dataset', type=Path); q.add_argument('log', type=Path)
    args = p.parse_args()
    if args.command == 'prepare': prepare(args)
    elif args.command == 'send': send(args)
    else: compare(args.dataset, args.log)


if __name__ == '__main__':
    main()
