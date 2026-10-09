"""Disconnected ROS node and fake IK only; no SDK import or hardware command."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ros2/arm_delta_cmd"))
rclpy = pytest.importorskip("rclpy")
pytest.importorskip("marvin_msgs.msg")
from arm_delta_cmd.delta_ctrl_node import DeltaCtrlNode
from std_msgs.msg import Float64MultiArray, MultiArrayDimension


@pytest.fixture
def receiver():
    rclpy.init(args=["--ros-args", "-p", "eef_publish_rate:=0.0", "-p", "enable_publish_joint_state:=false",
                     "-p", "tactile_guard_enabled:=false"])
    node = DeltaCtrlNode()
    receipts = []
    node.hil_receipt_pub = SimpleNamespace(publish=lambda msg: receipts.append(json.loads(msg.data)))
    yield node, receipts
    node.robot = None
    node.shutdown()
    node.destroy_node()
    rclpy.shutdown()


def tagged():
    message = Float64MultiArray(data=[.1] * 6)
    message.layout.dim = [MultiArrayDimension(label="hil:test-command", size=6, stride=6)]
    return message


def test_disconnected_receipt_and_wrong_frame_never_reaches_ik(receiver):
    node, receipts = receiver
    node.hil_delta_callback(tagged())
    assert not receipts[-1]["accepted"] and not receipts[-1]["execution_confirmed"]
    assert receipts[-1]["command_id"] == "hil:test-command"
    node.robot = node.kine = object()
    node.delta_frame = "tcp"
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda *a: pytest.fail("IK reached"))
    node.hil_delta_callback(tagged())
    assert not receipts[-1]["accepted"] and not node.traj_queue


def test_tagged_queue_acceptance_ik_failure_and_clamp_rejection(receiver):
    node, receipts = receiver
    node.robot = SimpleNamespace(clear_set=lambda: None, set_joint_cmd_pose=lambda **kw: True, send_cmd=lambda: None)
    node.kine = object()
    node.cur_joints = [0.] * 7
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda q, *a: (True, [x + .001 for x in q], None))
    node.hil_delta_callback(tagged())
    assert receipts[-1]["accepted"] and receipts[-1]["status"] == "queue_accepted"
    assert receipts[-1]["wire_action"] == [.1] * 6
    assert node.have_goal and not node.traj_queue
    for _ in range(35):
        node.ctrl_loop()
    assert not receipts[-1]['finished'] and node.have_goal
    node.last_policy_time -= 1. / node.policy_command_rate
    node.ctrl_loop()
    assert receipts[-1]['finished'] and receipts[-1]['status'] == 'velocity_window_sent'
    assert receipts[-1]['velocity_hold_continues'] and node.have_goal
    node.tk.solve_tcp_delta_ik = lambda *a: (False, None, None)
    node.hil_delta_callback(tagged())
    node.ctrl_loop()
    assert not receipts[-1]["accepted"] and receipts[-1]["status"] == "ik_failed" and not node.traj_queue
    node.tk.solve_tcp_delta_ik = lambda q, *a: (True, [x + 100. for x in q], None)
    node.hil_delta_callback(tagged())
    node.ctrl_loop()
    assert not receipts[-1]["accepted"] and receipts[-1]["status"] == "joint_clamp" and not node.traj_queue


def test_zero_stop_returns_explicit_partial_command_outcome(receiver):
    node, receipts = receiver
    node.robot = node.kine = object()
    node.cur_joints = [0.] * 7
    node.hil_delta_callback(tagged())
    node.hil_delta_callback(Float64MultiArray(data=[0.] * 6))
    assert receipts[-1]["status"] == "queue_cancelled" and receipts[-1]["finished"]
    assert receipts[-1]["accepted"] and not receipts[-1]["execution_confirmed"]


def test_tagged_zero_speed_finishes_without_sdk_motion(receiver):
    node, receipts = receiver
    node.robot = node.kine = object()
    message = tagged()
    message.data = [0.] * 6
    node.hil_delta_callback(message)
    assert receipts[-1]['finished'] and receipts[-1]['accepted']
    assert receipts[-1]['status'] == 'velocity_zero_stopped'
    assert not receipts[-1]['velocity_hold_continues']
    assert not node.have_goal


def test_tagged_manual_receipts_keep_human_route(receiver):
    node, receipts = receiver
    node.robot = SimpleNamespace(clear_set=lambda: None, set_joint_cmd_pose=lambda **kw: True, send_cmd=lambda: None)
    node.kine = object()
    node.cur_joints = [0.] * 7
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda q, *a: (True, [x + .001 for x in q], None))
    node.manual_delta_callback(tagged())
    assert receipts[-1]['accepted'] and receipts[-1]['action_source'] == 'human'
    assert node.queue_source == 'manual'
    node.last_manual_time -= 1. / node.manual_command_rate
    node.ctrl_loop()
    assert receipts[-1]['status'] == 'velocity_window_sent' and receipts[-1]['finished']
    node.manual_delta_callback(tagged())
    node.manual_delta_callback(Float64MultiArray(data=[0.] * 6))
    assert receipts[-1]['accepted'] and receipts[-1]['status'] == 'queue_cancelled'
    assert not node.have_goal


@pytest.mark.parametrize('manual', [False, True])
def test_late_other_channel_zero_cannot_cancel_selected_command(receiver, manual):
    node, receipts = receiver
    node.robot = node.kine = object()
    node.cur_joints = [0.] * 7
    active = tagged()
    node.hil_delta_callback(active, manual=manual)
    pending = node.hil_pending.copy()
    before = len(receipts)
    stop = Float64MultiArray(data=[0.] * 6)
    # Model the legal cross-topic delivery order: selected command first,
    # zero stop for the OLD channel later. Per-topic QoS does not order these.
    if manual:
        node.hil_delta_callback(stop)
    else:
        node.manual_delta_callback(stop)
    assert node.have_goal
    assert node.queue_source == ('manual' if manual else 'policy')
    assert node.hil_pending == pending
    assert not any(r['command_id'] == pending['command_id'] for r in receipts[before:])


@pytest.mark.parametrize('manual', [False, True])
def test_tagged_zero_is_selected_action_and_can_take_over_other_channel(receiver, manual):
    node, receipts = receiver
    node.robot = node.kine = object()
    node.cur_joints = [0.] * 7
    node.hil_delta_callback(tagged(), manual=not manual)
    zero = tagged()
    zero.data = [0.] * 6
    zero.layout.dim[0].label = 'hil:selected-zero'
    node.hil_delta_callback(zero, manual=manual)
    assert not node.have_goal
    assert node.queue_source == ('manual' if manual else 'policy')
    assert receipts[-1]['command_id'] == 'hil:selected-zero'
    assert receipts[-1]['accepted'] and receipts[-1]['status'] == 'velocity_zero_stopped'


def test_sdk_rejection_receipt_preserves_target_feedback_and_native_result(receiver):
    node, receipts = receiver
    feedback = [1.] * 7
    node.robot = SimpleNamespace(clear_set=lambda: True, set_joint_cmd_pose=lambda **kw: False,
        send_cmd=lambda: pytest.fail('must not send a rejected target'),
        subscribe=lambda _: dict(states=[dict(cur_state=3, cmd_state=3, err_code=17)],
            outputs=[dict(fb_joint_pos=feedback, frame_serial=123, fb_joint_cmd=[2.]*7)]))
    node.dcss = object()
    node.kine = object()
    node.cur_joints = [2.] * 7
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda q, *a: (True, [x+.001 for x in q], None))
    node.hil_delta_callback(tagged(), manual=True)
    node.ctrl_loop()
    assert not node.have_goal and receipts[-1]['status'] == 'sdk_rejected'
    details = receipts[-1]['diagnostics']
    assert details['sdk_call'] == 'set_joint_cmd_pose' and details['sdk_return'] is False
    assert details['controller_state']['err_code'] == 17
    assert details['feedback_frame_serial'] == 123
    assert details['feedback_joint_deg'] == feedback
    assert details['target_joint_deg'] == pytest.approx([2.001]*7)
    assert details['max_target_feedback_error_deg'] == pytest.approx(1.001)
    assert details['queue_source'] == 'manual'
