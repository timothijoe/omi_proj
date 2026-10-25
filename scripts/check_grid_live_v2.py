"""Synthetic ROS isolation/visual check. Never runs in the hardware domain 13.

Run using the viewer's Python with ROS sourced. Output directory must be new.
All test publishers (images, pose, commands, receipts) are synthetic in an isolated
test domain. The viewer itself must never publish command messages.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--domain', type=int, default=221)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--model', action='store_true')
    args = parser.parse_args()
    if not 200 <= args.domain <= 232:
        parser.error('Test domain must be 200..232')
    args.output.mkdir(parents=True, exist_ok=False)
    args.output = args.output.resolve()
    os.environ.update(ROS_DOMAIN_ID=str(args.domain), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='0')
    root = Path(__file__).resolve().parents[1]
    os.environ['FASTRTPS_DEFAULT_PROFILES_FILE'] = str(root/'ros2/omi_sensors/config/live_dashboard_network.xml')
    import numpy as np
    import rclpy
    from sensor_msgs.msg import Image
    from std_msgs.msg import Header, String, Float64MultiArray, MultiArrayDimension
    from geometry_msgs.msg import PoseStamped
    from rcl_interfaces.srv import GetParameters
    from rcl_interfaces.msg import ParameterValue
    from omi_hil_rl.real.grid_live_v2_core import NS, panels, header_stamp_cdr
    rclpy.init()
    node = rclpy.create_node('omi_v2_synthetic_check')
    items = panels()
    publishers = {p.source: node.create_publisher(Image, p.source, 1) for p in items}
    received, headers = Counter(), {}
    state = {}
    control = {}
    mode = dict(bad=False, missing=False, sequence=0, bad_command=False, missing_command=False, missing_camera=False)
    qos = rclpy.qos.QoSProfile(depth=1, reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT)
    for p in items:
        if p.kind != 'direct':
            def receive(data, key=p.key):
                received[key] += 1
                headers[key] = header_stamp_cdr(data)
            node.create_subscription(Image, p.topic, receive, qos, raw=True)
    def status(msg):
        state.clear()
        state.update(json.loads(msg.data))
    node.create_subscription(String, NS+'/status', status, 1)
    def control_status(msg):
        control.clear();control.update(json.loads(msg.data))
    node.create_subscription(String, NS+'/control/status', control_status, 1)
    command_topics = dict(human='/omi/controller_test/decision', policy='/omi/action/decision')
    def parameters(request, response):
        values = dict(delta_topic=command_topics['policy'], manual_delta_topic=command_topics['human'], delta_frame='base', arm='A')
        response.values = [ParameterValue(type=4, string_value=values[name]) for name in request.names]
        return response
    node.create_service(GetParameters, '/delta_ctrl_node/get_parameters', parameters)
    command_pubs = {key: node.create_publisher(Float64MultiArray, topic, 1) for key, topic in command_topics.items()}
    receipt_pub = node.create_publisher(String, '/omi/action/receipt', 1)
    pose_pub = node.create_publisher(PoseStamped, '/tj/info/eef_left', 1)
    def pose_tick():
        pose = PoseStamped();pose.header.stamp = node.get_clock().now().to_msg();pose.header.frame_id = 'base_link'
        pose.pose.position.x = .628;pose.pose.position.y = -.034;pose.pose.position.z = .8;pose.pose.orientation.w = 1.
        pose_pub.publish(pose)
    node.create_timer(.02, pose_tick)
    def command_tick():
        for key, values in [('human', [-.75, .25, .5, -.3, .2, -.1]), ('policy', [.25, -.5, .75, .1, -.2, .3])]:
            if key == 'human' and mode['missing_command']:
                continue
            msg = Float64MultiArray()
            msg.data = [float('nan')]*6 if key == 'human' and mode['bad_command'] else values
            msg.layout.dim = [MultiArrayDimension(label='hil:fixture', size=6, stride=6)]
            command_pubs[key].publish(msg)
        receipt_pub.publish(String(data=json.dumps(dict(command_id='hil:fixture', action_source='human',
            accepted=True, status='queue_accepted', execution_confirmed=False))))
    node.create_timer(.1, command_tick)
    # Grid colours and moving bars make fresh synthetic frames visually obvious.
    def publish():
        mode['sequence'] += 1
        header = Header()
        header.stamp = node.get_clock().now().to_msg()
        header.frame_id = 'SYNTHETIC_TEST_ONLY'
        for topic, pub in publishers.items():
            if mode['missing_camera'] and topic == '/camera/camera/color/image_raw':
                continue
            if mode['missing'] and topic.endswith('/a/shear'):
                continue
            if topic.endswith(('deformation', 'shear')):
                value = np.zeros((16, 24, 2), np.float32)
                value[:, :, 0] = .5*np.sin(mode['sequence']/20)
                value[:, :, 1] = .25
                if mode['bad'] and topic.endswith('/a/deformation'):
                    value[0, 0, 0] = np.nan
                encoding = '32FC2'
            elif topic.endswith('/depth'):
                value = np.linspace(0, .3, 16*24, dtype=np.float32).reshape(16, 24)
                encoding = '32FC1'
            else:
                size = (128, 128) if 'roi' in topic else (240, 320) if 'tactile' in topic else (480, 640)
                value = np.zeros((*size, 3), np.uint8)
                value[:, :, 0] = np.arange(size[1], dtype=np.uint8)
                value[:, :, 1] = 90 if '/a/' in topic else 170
                value[:, :, 2] = 70
                start = (mode['sequence']*4) % size[1]
                value[:, start:start+10] = 255
                encoding = 'rgb8'
            message = Image()
            message.header = header
            message.height, message.width = value.shape[:2]
            message.encoding = encoding
            message.is_bigendian = False
            message.step = value.strides[0]
            message.data = value.tobytes()
            pub.publish(message)
    node.create_timer(1/30, publish)
    if args.model:
        from marvin_msgs.msg import Jointfeedback
        joint_pub = node.create_publisher(Jointfeedback, '/tj/info/joint_feedback', 1)
        def robot():
            stamp = node.get_clock().now().to_msg()
            msg = Jointfeedback();msg.header.stamp = stamp
            msg.positions = [0.]*14;msg.positions[1] = .1*np.sin(time.monotonic())
            joint_pub.publish(msg)
        node.create_timer(.02, robot)
    log = (args.output/'launcher.log').open('w')
    cmd = ['bash', str(root/'scripts/view_grid_observation_live_v2.sh'), '--domain', str(args.domain),
           '--model-mode', 'corrected' if args.model else 'none', '--output', str(args.output/'viewer'), '--hz', '10']
    if not args.gui:
        cmd.append('--no-rviz')
    child = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    frozen = None
    checks = {}
    def pump(seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError('Viewer exited; inspect launcher/role logs')
            rclpy.spin_once(node, timeout_sec=.01)
    def save(name):
        (args.output/(name+'.json')).write_text(json.dumps(state, indent=2)+'\n')
    try:
        deadline = time.monotonic()+25
        while time.monotonic() < deadline and not all(received[p.key] >= 2 for p in items if p.kind != 'direct'):
            pump(.25)
        assert all(received[p.key] >= 2 for p in items if p.kind != 'direct'), dict(received)
        pump(3)
        save('nominal')
        checks['all_derived_panels_publish'] = dict(received)
        assert all(state['workers'][p.key]['state'] == 'OK' for p in items if p.kind != 'direct')
        assert control['routes'] == command_topics
        assert control['signals']['eef']['value']['xyz_mm'] == [628., -34., 800.]
        assert control['signals']['human']['value']['components'] == [-.75, .25, .5, -.3, .2, -.1]
        assert control['signals']['policy']['value']['components'] == [.25, -.5, .75, .1, -.2, .3]
        checks['control_bar_routes_pose_commands'] = True
        mode['bad_command'] = True
        pump(1)
        assert control['signals']['human']['state'] == 'BAD_DATA'
        assert control['signals']['policy']['state'] == 'LIVE'
        mode['bad_command'] = False
        pump(.5)
        mode['missing_command'] = True
        pump(1)
        assert control['signals']['human']['state'] == 'STALE'
        assert control['signals']['human']['value']['components'][0] == -.75
        assert control['signals']['policy']['state'] == 'LIVE'
        mode['missing_command'] = False
        checks['control_bar_bad_and_stale_lane_isolated'] = True
        # Prefix parsing must match the actual ROS serializer's Header.
        assert all(v is not None for v in headers.values())
        mode['bad'] = True
        pump(2)
        assert state['workers']['a_deformation']['state'] == 'BAD_DATA'
        assert state['workers']['b_shear']['state'] == 'OK'
        save('bad_field')
        checks['bad_field_isolated'] = True
        mode['bad'] = False
        pump(1)
        frozen = state['workers']['a_deformation']['pid']
        previous = dict(received)
        os.kill(frozen, signal.SIGSTOP)
        pump(3)
        from omi_hil_rl.real.grid_live_v2_core import panel_health
        worker = state['workers']['a_deformation']
        assert panel_health(worker, worker['heartbeat_received_mono_ns'], time.monotonic_ns()) == 'WORKER_SILENT'
        assert received['b_shear'] > previous['b_shear']+5
        assert state['sources']['/omi/tactile_grid24x16/a/deformation']['state'] == 'RECEIVING'
        save('frozen_worker')
        checks['frozen_worker_isolated'] = True
        os.kill(frozen, signal.SIGCONT);frozen = None
        pump(1)
        mode['missing'] = True
        pump(2)
        assert state['sources']['/omi/tactile_grid24x16/a/shear']['state'] == 'STALE'
        assert state['workers']['a_shear']['state'] == 'STALE'
        assert state['workers']['b_shear']['state'] == 'OK'
        save('source_stopped')
        checks['source_loss_distinguished'] = True
        mode['missing'] = False
        pump(1)
        mode['missing_camera'] = True
        pump(1.5)
        assert state['workers']['camera_roi']['state'] == 'STALE'
        checks['roi_stale_badge_state'] = True
        mode['missing_camera'] = False
        pump(1)
        dead = state['workers']['b_depth']['pid']
        previous = dict(received)
        os.kill(dead, signal.SIGTERM)
        pump(3)
        assert received['a_depth'] > previous['a_depth']+5
        checks['worker_exit_does_not_close_viewer'] = True
        save('dead_worker')
        if args.gui:
            # Give the window a settled scene. Capture via Qt/X11 below, no hardware domain.
            pump(3)
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtGui import QWindow
            app = QApplication.instance() or QApplication([])
            screen = app.primaryScreen()
            tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
            match = next((re.search(r'0x[0-9a-f]+', line) for line in tree.splitlines()
                          if str(args.output/'viewer/live.rviz') in line), None)
            assert match, 'RViz window missing from X11 tree'
            wid = int(match.group(), 16)
            foreign = QWindow.fromWinId(wid)
            foreign.raise_()
            foreign.requestActivate()
            deadline = time.monotonic()+1
            while time.monotonic() < deadline:
                app.processEvents()
                pump(.05)
            assert screen.grabWindow(wid).save(str(args.output/'rviz.png'))
            checks['gui_screenshot'] = 'rviz.png'
        # Command subscribers create graph entries too; check actual publishers.
        unexpected = []
        for topic in command_topics.values():
            unexpected.extend((topic, e.node_name) for e in node.get_publishers_info_by_topic(topic)
                              if e.node_name != 'omi_v2_synthetic_check')
        assert not unexpected, unexpected
        checks['viewer_command_publishers'] = unexpected
    finally:
        if frozen is not None:
            os.kill(frozen, signal.SIGCONT)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        log.close()
        node.destroy_node()
        rclpy.shutdown()
    process_file = args.output/'viewer/processes.json'
    states = json.loads(process_file.read_text())
    leftovers = [v['pid'] for v in states.values() if Path(f'/proc/{v["pid"]}').exists()]
    assert not leftovers, leftovers
    checks['child_processes_remaining'] = leftovers
    checks['passed'] = True
    (args.output/'report.json').write_text(json.dumps(checks, indent=2)+'\n')
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
