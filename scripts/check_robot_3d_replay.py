#!/usr/bin/env python3
"""Read-only isolated-domain integration check; --gui additionally opens RViz."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import numpy as np
import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from sensor_msgs.msg import JointState, Image
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag', type=Path)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--domain', type=int, default=98)
    parser.add_argument('--seconds', type=float, default=42)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'local/robot_state/3d_check'
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(ROS_DOMAIN_ID=str(args.domain), OMI_TACTILE_ROS_DOMAIN_ID=str(args.domain),
                      ROS_LOCALHOST_ONLY='1', ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    rclpy.init()
    node = rclpy.create_node('robot_3d_check')
    result = dict(joint_messages=0, tf_messages=0, image_messages=0, moving=False,
                  loop_seen=False, description=False, static_tf=False, states=[])
    previous_q, previous_ref = [None], [0]
    def joints(msg):
        q = np.array(msg.position)
        assert len(msg.name) == 14 and q.shape == (14,) and np.isfinite(q).all()
        if previous_q[0] is not None and not np.allclose(previous_q[0], q):
            result['moving'] = True
        previous_q[0] = q
        result['joint_messages'] += 1
    def tf(msg):
        assert all(t.child_frame_id.startswith('omi_replay_') for t in msg.transforms)
        result['tf_messages'] += 1
    def static(msg):
        result['static_tf'] = any(t.header.frame_id == 'omi_replay_world' for t in msg.transforms)
    def description(msg):
        result['description'] = '<robot ' in msg.data and 'left_joint7' in msg.data
    def status(msg):
        value = json.loads(msg.data)
        ref = value.get('reference_ns', 0)
        if ref and ref < previous_ref[0]:
            result['loop_seen'] = True
        previous_ref[0] = ref
        if value['state'] not in result['states']:
            result['states'].append(value['state'])
    def image(msg):
        result['image_messages'] += 1
    transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                           reliability=ReliabilityPolicy.RELIABLE)
    node.create_subscription(JointState, '/omi/replay_3d/joint_states', joints, 2)
    node.create_subscription(TFMessage, '/omi/replay_3d/tf', tf, 10)
    node.create_subscription(TFMessage, '/omi/replay_3d/tf_static', static, transient)
    node.create_subscription(String, '/omi/replay_3d/robot_description', description, transient)
    node.create_subscription(String, '/omi/replay_3d/status', status, 2)
    node.create_subscription(Image, '/omi/observation_robot/dashboard', image, 1)
    command = ['bash', str(root/'scripts/view_observation_robot_3d_bag.sh'), str(args.bag.resolve()), '2']
    if not args.gui:
        command.append('--no-rviz')
    with (output/'run.log').open('w') as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        try:
            start, captured = time.monotonic(), False
            while time.monotonic()-start < args.seconds:
                rclpy.spin_once(node, timeout_sec=.1)
                if process.poll() is not None:
                    raise RuntimeError('3D launcher exited; inspect run.log')
                if args.gui and not captured and time.monotonic()-start > 18:
                    from PIL import ImageGrab
                    ImageGrab.grab().save(output/'rviz_desktop.png')
                    captured = True
            topics = [name for name, _ in node.get_topic_names_and_types()]
            result['no_control_topics'] = not any(t.startswith('/tj/control/') for t in topics)
            result['no_global_joint_states'] = '/joint_states' not in topics
            if args.gui:
                result['rviz_notice_subscription'] = any('rviz' in x.node_name for x in
                    node.get_subscriptions_info_by_topic('/omi/replay_3d/notice'))
        finally:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                result['forced_kill'] = True
            node.destroy_node()
            rclpy.shutdown()
            (output/'report.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    assert all(result[k] for k in ('moving','loop_seen','description','static_tf','no_control_topics','no_global_joint_states'))
    assert result['tf_messages'] > 10 and result['image_messages'] > 10 and not result.get('forced_kill')
    if args.gui:
        assert result['rviz_notice_subscription']


if __name__ == '__main__':
    main()
