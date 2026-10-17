#!/usr/bin/env python3
"""Passive ROS command/feedback recording. No robot command publisher or SDK."""
import argparse
from collections import Counter, deque
from datetime import datetime
import json
import math
from pathlib import Path
import time


def values(sequence):
    return [float(x) if math.isfinite(float(x)) else None for x in sequence]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=45.)
    parser.add_argument('--wait-seconds', type=float, default=300.)
    parser.add_argument('--trigger', choices=('motion', 'immediate'), default='motion')
    parser.add_argument('--manual-topic', default='/omi/controller_test/decision')
    args = parser.parse_args()
    if not all(math.isfinite(v) and 0 < v <= 600 for v in (args.seconds, args.wait_seconds)):
        parser.error('durations must be finite and in (0,600]')

    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rcl_interfaces.msg import Log
    from rcl_interfaces.srv import GetParameters
    from std_msgs.msg import Float64MultiArray, String
    from geometry_msgs.msg import PoseStamped
    from marvin_msgs.msg import Jointfeedback

    rows, counts, errors = [], Counter(), []
    before_trigger = deque(maxlen=2000)
    origin = time.monotonic()
    trigger = origin if args.trigger == 'immediate' else None
    configuration = {}
    finished = 'interrupted'
    rclpy.init()
    node = rclpy.create_node('omi_control_response_recorder', enable_rosout=False)

    def record(kind, data, starts_motion=False):
        nonlocal trigger
        now = time.monotonic()
        row = dict(t_s=now-origin, kind=kind, **data)
        counts[kind] += 1
        if trigger is None:
            while before_trigger and row['t_s']-before_trigger[0]['t_s'] > 2.:
                before_trigger.popleft()
            if starts_motion:
                trigger = now
                rows.extend(before_trigger)
                before_trigger.clear()
                print(f'检测到首条非零手动指令，开始记录 {args.seconds:g} 秒。', flush=True)
            else:
                before_trigger.append(row)
                return
        rows.append(row)

    def command(msg):
        data = values(msg.data)
        valid = len(data) == 6 and all(x is not None for x in data)
        record('manual_command', dict(data=data, valid=valid), valid and any(data))

    def header(msg):
        return dict(source_stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,
                    frame_id=msg.header.frame_id)

    def joint(msg):
        record('joint_feedback', dict(**header(msg), positions_rad=values(msg.positions),
                                      velocities_rad_s=values(msg.velocities), efforts=values(msg.efforts)))

    def eef(msg):
        p, q = msg.pose.position, msg.pose.orientation
        record('eef_feedback', dict(**header(msg), position_m=values([p.x,p.y,p.z]),
                                    quaternion_xyzw=values([q.x,q.y,q.z,q.w])))

    def ros_log(msg):
        if msg.name == 'delta_ctrl_node' and msg.level >= Log.WARN:
            record('receiver_log', dict(level=msg.level, text=msg.msg))

    qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT)
    node.create_subscription(Float64MultiArray, args.manual_topic, command, 100)
    node.create_subscription(Jointfeedback, '/tj/info/joint_feedback', joint, qos)
    node.create_subscription(PoseStamped, '/tj/info/eef_left', eef, qos)
    node.create_subscription(String, '/omi/action/receipt',
                             lambda msg: record('receipt', dict(text=msg.data)), 100)
    node.create_subscription(Log, '/rosout', ros_log, qos)
    print('只读记录器已启动：没有动作发布者，不加载机器人 SDK。', flush=True)
    try:
        client = node.create_client(GetParameters, '/delta_ctrl_node/get_parameters')
        names = ['arm','ctrl_rate','manual_command_rate','manual_timeout','start_mode',
                 'delta_frame','manual_delta_topic','imp_k','imp_d']
        if client.wait_for_service(timeout_sec=3.):
            future = client.call_async(GetParameters.Request(names=names))
            rclpy.spin_until_future_complete(node, future, timeout_sec=3.)
            if future.done() and future.result() is not None:
                for name, v in zip(names, future.result().values):
                    configuration[name] = {1:v.bool_value,2:v.integer_value,3:v.double_value,
                                           4:v.string_value,8:list(v.double_array_value)}.get(v.type)
            else:
                errors.append('receiver parameter query timed out')
        else:
            errors.append('receiver parameter service unavailable')
        if configuration.get('manual_delta_topic') not in (None, args.manual_topic):
            raise ValueError('Receiver manual topic differs; use --manual-topic '+configuration['manual_delta_topic'])
        print('接收端配置：'+json.dumps(configuration, ensure_ascii=False), flush=True)
        print(('就绪：等待首条非零指令，最多等待 '+str(args.wait_seconds)+' 秒。'
               if args.trigger == 'motion' else '正在定时采样。')+
              'Ctrl+C可提前保存。', flush=True)
        last_notice = time.monotonic()
        while rclpy.ok():
            now = time.monotonic()
            if trigger is not None and now-trigger >= args.seconds:
                finished = 'duration_complete'
                break
            if trigger is None and now-origin >= args.wait_seconds:
                finished = 'no_motion_timeout'
                break
            rclpy.spin_once(node, timeout_sec=.02)
            if now-last_notice >= 5.:
                remaining = max(0., args.seconds-(now-trigger)) if trigger is not None else None
                print(('录制剩余 %.1f 秒' % remaining if remaining is not None else '等待动作')+
                      '；消息计数：'+json.dumps(dict(counts)), flush=True)
                last_notice = now
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
        finished = 'error'
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    if trigger is None:
        rows = list(before_trigger)
    folder = Path(__file__).resolve().parents[1] / 'local/diagnostics/control_response'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report = dict(schema='omi-control-response-v1', readonly=True, settings=vars(args),
                  receiver_parameters=configuration, result=finished, errors=errors,
                  trigger_t_s=None if trigger is None else trigger-origin,
                  received_counts=dict(counts), stored_counts=dict(Counter(row['kind'] for row in rows)),
                  clock='local monotonic callback receive time; source headers kept separately',
                  limitations='No SDK targets or SDK send times. Not a hardware/physical button timestamp. Best-effort feedback can lose samples.',
                  rows=rows)
    with path.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, allow_nan=False)
    print('已保存：'+str(path), flush=True)
    if trigger is None:
        print('未捕获有效非零手动指令，本文件不能作为运动响应测试。')
    if errors:
        print('记录问题：'+'; '.join(errors))


if __name__ == '__main__':
    main()
