"""Disconnected receiver and fake-IK tests; never import the vendor SDK."""
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ros2/arm_delta_cmd'))
rclpy = pytest.importorskip('rclpy')
pytest.importorskip('marvin_msgs.msg')
from arm_delta_cmd.delta_ctrl_node import DeltaCtrlNode
from std_msgs.msg import Float64MultiArray


@pytest.fixture
def node():
    rclpy.init(args=['--ros-args', '-p', 'eef_publish_rate:=0.0',
                     '-p', 'enable_publish_joint_state:=false',
                     '-p', 'tactile_guard_enabled:=false'])
    instance = DeltaCtrlNode()
    yield instance
    instance.robot = None
    instance.shutdown()
    instance.destroy_node()
    rclpy.shutdown()


def test_default_does_not_load_sdk_or_connect(node):
    from marvin_msgs.msg import Jointfeedback
    assert set(Jointfeedback.get_fields_and_field_types()) == {
        'header', 'positions', 'velocities', 'efforts'}
    assert not node.connect_on_start
    assert not node.motion_authorized
    assert node.robot is None
    services = {service.srv_name for service in node.services}
    assert '/delta_ctrl_node/home_poses' in services
    assert '/delta_ctrl_node/set_keyboard_control' not in services
    assert 'fx_robot' not in sys.modules
    assert 'fx_kine' not in sys.modules
    with pytest.raises(RuntimeError, match='authorization'):
        node._connect_robot()
    node.delta_callback(Float64MultiArray(data=[1.0] * 6))
    assert not node.traj_queue


def test_connect_flag_alone_is_rejected():
    rclpy.init(args=['--ros-args', '-p', 'connect_on_start:=true'])
    try:
        with pytest.raises(ValueError, match='motion_authorized'):
            DeltaCtrlNode()
        assert 'fx_robot' not in sys.modules
    finally:
        rclpy.shutdown()


def test_fake_ik_policy_speed_hold_and_command_anchor(node):
    calls, events, sent = [], [], []
    def solve(q, translation, abc, frame):
        calls.append((list(q), translation, abc, frame))
        events.append('ik')
        return True, [v + .1 for v in q], None
    node.robot = SimpleNamespace(clear_set=lambda: None,
        set_joint_cmd_pose=lambda **kw: sent.append(kw['joints']) or True,
        send_cmd=lambda: events.append('send'))
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=solve)
    node.cur_joints = [4.] * 7
    node.delta_callback(Float64MultiArray(data=[2., 4., 6., 8., 10., 12.]))
    assert not calls and not node.traj_queue
    for i in range(35):
        node.ctrl_loop()
        assert events == ['ik', 'send'] * (i + 1)
    assert node.have_goal and len(sent) == 35
    assert calls[0] == ([4.] * 7, [.1, .2, .3], [.4, .5, .6], 0)
    node.delta_callback(Float64MultiArray(data=[0.] * 6))
    node.ctrl_loop()
    assert len(sent) == 35 and not node.have_goal


def test_nonfinite_command_never_reaches_ik(node):
    node.robot = object()
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda *a: pytest.fail('IK called'))
    node.delta_callback(Float64MultiArray(data=[float('nan')] + [0.] * 5))
    assert not node.traj_queue


def test_home_fk_reads_feedback_and_converts_target_radians(node):
    import json
    import math
    from std_srvs.srv import Trigger
    calls = []
    node.robot = SimpleNamespace(subscribe=lambda _: {'outputs': [dict(fb_joint_pos=[2.]*7)]})
    node.dcss = object()
    def fk(joints):
        calls.append(joints)
        return [[1., 0., 0., 10.], [0., 1., 0., 20.],
                [0., 0., 1., 30.], [0., 0., 0., 1.]]
    node.kine = SimpleNamespace(fk=fk)
    result = node.home_poses_callback(Trigger.Request(), Trigger.Response())
    assert result.success
    assert calls[0] == [2.]*7
    assert calls[1] == pytest.approx([math.degrees(v) for v in [
        1.36784420538524, -1.3972774378908723, -0.8460047216729514,
        -1.4080845166192213, -0.26412765702130986, -0.1478974554847475,
        0.6224018645536978]])
    assert json.loads(result.message)['target'][0][3] == .01


def test_mount_matches_left_policy_inverse(node):
    # SDK base -> root: Rx(-90); root -> SDK used by policy: Rx(+90).
    # Load the pure conversion module without the training package's Gym extras.
    spec = importlib.util.spec_from_file_location(
        'omi_sdk_action_audit', ROOT / 'src/omi_hil_rl/real/sdk_action.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Inspect the receiver transform directly, independent of physical calibration.
    node.root_mount = node._root_mount_matrix()
    pose = [[1., 0., 0., 1000.], [0., 1., 0., 2000.],
            [0., 0., 1., 3000.], [0., 0., 0., 1.]]
    transformed, frame = node._transform_to_root(pose)
    assert [row[3] for row in transformed[:3]] == pytest.approx([1., 3.2005, -0.879])
    assert frame == 'base_link'
    root_delta = [transformed[i][3] - node.root_mount[i][3] for i in range(3)]
    assert module.output_action(root_delta + [0., 0., 0.], 'sdk-x-forward-z-left')[:3] == pytest.approx(
        [1000., 2000., 3000.])


def install_fake_guard_robot(node):
    """Install a fixed baseline and fake robot; absolutely no SDK/network calls."""
    import time
    from arm_delta_cmd.tactile_guard import TactileGuard
    node.tactile_guard = TactileGuard(enabled=True, timeout=10.)
    now = time.monotonic()
    for i in range(20):
        for side in ('a', 'b'):
            node.tactile_guard.update(side, [0.] * 6, now - .57 + i * .03)
    assert node.tactile_guard.capture_baseline(now)[0]
    node.guard_generation = node.tactile_guard.generation
    node.pending_guard_hold = False
    sent, ik_calls = [], []
    node.robot = SimpleNamespace(
        subscribe=lambda _: {'outputs': [dict(fb_joint_pos=[2.] * 7)]},
        clear_set=lambda: None,
        set_joint_cmd_pose=lambda **kw: sent.append(kw['joints']) or True,
        send_cmd=lambda: None)
    node.dcss = object()
    node.kine = object()
    def solve(q, translation, abc, frame):
        ik_calls.append((translation, abc, frame))
        return True, [q[0] + translation[0]] + q[1:], None
    node.tk = SimpleNamespace(solve_tcp_delta_ik=solve)
    return sent, ik_calls


def test_receiver_trip_clears_old_queue_and_holds_feedback_before_retreat(node):
    from geometry_msgs.msg import WrenchStamped
    sent, calls = install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[1., 0., 0., 0., 0., 0.]))
    assert node.have_goal and not node.traj_queue
    msg = WrenchStamped()
    msg.wrench.force.x = -3.
    node.tactile_callback('a', msg)
    assert not node.traj_queue and not node.have_goal
    assert node.pending_guard_hold
    node.delta_callback(Float64MultiArray(data=[-1., 5., 6., 7., 8., 9.]))
    assert not node.traj_queue  # reference must be held/reanchored first
    node.ctrl_loop()
    assert sent == [[2.] * 7]
    assert node.cur_joints == [2.] * 7 and not node.pending_guard_hold
    calls.clear()
    node.delta_callback(Float64MultiArray(data=[-1., 5., 6., 7., 8., 9.]))
    assert node.queue_is_retreat and not node.traj_queue
    assert not calls
    node.ctrl_loop()
    assert calls[0] == ([-.01, 0., 0.], [0., 0., 0.], 0)
    assert sent[-1][0] < 2.


def test_blocked_forward_cancels_even_an_existing_retreat(node):
    import time
    install_fake_guard_robot(node)
    node.tactile_guard.update('a', [3., 0., 0., 0., 0., 0.], time.monotonic())
    node.ctrl_loop()  # feedback hold
    node.delta_callback(Float64MultiArray(data=[-.1, 0., 0., 0., 0., 0.]))
    assert node.have_goal
    node.delta_callback(Float64MultiArray(data=[1., 0., 0., 0., 0., 0.]))
    assert not node.have_goal and not node.traj_queue and node.pending_guard_hold


def test_receiver_watchdog_stops_queue_without_any_new_command(node):
    import time
    sent, _ = install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[1., 0., 0., 0., 0., 0.]))
    node.tactile_guard.latest['b'] = (time.monotonic() - 11., (0.,) * 6)
    node.ctrl_loop()
    assert not node.have_goal and not node.traj_queue
    assert sent == [[2.] * 7]  # no old insertion target was sent
    node.delta_callback(Float64MultiArray(data=[-1., 0., 0., 0., 0., 0.]))
    assert not node.have_goal


def test_failed_feedback_hold_keeps_all_actions_blocked(node):
    import time
    install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[1., 0., 0., 0., 0., 0.]))
    node.tactile_guard.update('a', [3., 0., 0., 0., 0., 0.], time.monotonic())
    node.robot.subscribe = lambda _: None
    node.ctrl_loop()
    assert node.pending_guard_hold
    node.delta_callback(Float64MultiArray(data=[-1., 0., 0., 0., 0., 0.]))
    assert not node.have_goal


def test_guard_default_is_disabled_and_enabled_tcp_frame_is_rejected():
    rclpy.init(args=['--ros-args', '-p', 'eef_publish_rate:=0.0',
                     '-p', 'enable_publish_joint_state:=false'])
    instance = None
    try:
        instance = DeltaCtrlNode()
        assert not instance.tactile_guard.enabled
        assert instance.tactile_guard.baseline is None
        assert instance.robot is None
    finally:
        if instance is not None:
            instance.destroy_node()
        rclpy.shutdown()
    rclpy.init(args=['--ros-args', '-p', 'delta_frame:=tcp', '-p', 'tactile_guard_enabled:=true'])
    try:
        with pytest.raises(ValueError, match='delta_frame=base'):
            DeltaCtrlNode()
    finally:
        rclpy.shutdown()


def test_retreat_speed_limit_survives_single_split_configuration(node):
    import time
    _, calls = install_fake_guard_robot(node)
    node.delta_splits = 1
    node.tactile_guard.update('a', [3., 0., 0., 0., 0., 0.], time.monotonic())
    node.ctrl_loop()
    node.delta_callback(Float64MultiArray(data=[-10., 0., 0., 0., 0., 0.]))
    assert node.have_goal and not node.traj_queue and not calls
    node.ctrl_loop()
    assert len(calls) == 1
    assert abs(calls[0][0][0]) * node.ctrl_rate <= node.tactile_retreat_speed_mm_s


@pytest.mark.parametrize('fault', ['overload', 'missing', 'stale', 'invalid', 'unarmed'])
def test_manual_full_action_bypasses_every_guard_condition(node, fault):
    import time
    sent, calls = install_fake_guard_robot(node)
    if fault == 'overload':
        node.tactile_guard.update('a', [3., 0., 0., 0., 0., 0.], time.monotonic())
    elif fault == 'missing':
        del node.tactile_guard.latest['b']
    elif fault == 'stale':
        node.tactile_guard.latest['b'] = (time.monotonic() - 11., (0.,) * 6)
    elif fault == 'invalid':
        node.tactile_guard.update('b', [float('nan')] * 6, time.monotonic())
    else:
        node.tactile_guard.baseline = None
    node.pending_guard_hold = True  # manual takeover bypasses even a pending model hold
    node.manual_delta_callback(Float64MultiArray(data=[2., 4., 6., 8., 10., 12.]))
    assert not calls
    assert node.queue_source == 'manual'
    assert node.have_goal and not node.pending_guard_hold
    node.ctrl_loop()
    assert sent and node.have_goal
    assert calls[0] == ([.1, .2, .3], [.4, .5, .6], 0)
    node.delta_callback(Float64MultiArray(data=[1.] * 6))
    assert node.have_goal and node.queue_source == 'manual'  # blocked policy cannot stop manual
    node.manual_delta_callback(Float64MultiArray(data=[0.] * 6))
    assert not node.have_goal and not node.traj_queue


def test_new_trip_does_not_clear_running_manual_queue(node):
    from geometry_msgs.msg import WrenchStamped
    sent, _ = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[1., 2., 3., 4., 5., 6.]))
    msg = WrenchStamped()
    msg.wrench.force.x = 3.
    node.tactile_callback('a', msg)
    assert not node.traj_queue and node.have_goal and not node.pending_guard_hold
    node.ctrl_loop()
    assert sent and node.have_goal and not node.traj_queue


@pytest.mark.parametrize('failure', ['ik', 'envelope', 'sdk'])
def test_incremental_failure_stops_remaining_steps_without_advancing_anchor(node, failure):
    sent = []
    node.robot = SimpleNamespace(
        clear_set=lambda: None,
        set_joint_cmd_pose=lambda **kw: sent.append(kw['joints']) or True,
        send_cmd=lambda: None)
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda q, *args: (True, [v + .1 for v in q], None))
    node.delta_callback(Float64MultiArray(data=[1.] * 6))
    node.ctrl_loop()
    anchor = list(node.cur_joints)
    if failure == 'ik':
        node.tk.solve_tcp_delta_ik = lambda *args: (False, None, None)
    elif failure == 'envelope':
        node.tcp_anchor = [0., 0., 0.]
        node.envelope_radius_mm = 1.
        node.kine = SimpleNamespace(fk=lambda _: [[1., 0., 0., 2.], [0., 1., 0., 0.],
                                                [0., 0., 1., 0.], [0., 0., 0., 1.]])
    else:
        node.robot.set_joint_cmd_pose = lambda **kw: False
    node.ctrl_loop()
    assert sent == [anchor]
    assert node.cur_joints == anchor
    assert not node.traj_queue and not node.have_goal
    node.ctrl_loop()
    assert sent == [anchor]


def test_incremental_timeout_never_runs_ik(node):
    import time
    node.robot = SimpleNamespace()
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda *args: pytest.fail('IK after timeout'))
    node.delta_callback(Float64MultiArray(data=[1.] * 6))
    node.last_policy_time = time.monotonic() - 1.
    node.ctrl_loop()
    assert not node.traj_queue and not node.have_goal


def test_incremental_joint_limit_anchors_next_ik_to_sent_point(node):
    refs, sent = [], []
    def solve(q, *args):
        refs.append(list(q))
        return True, [v + 10. for v in q], None
    node.robot = SimpleNamespace(clear_set=lambda: None,
        set_joint_cmd_pose=lambda **kw: sent.append(kw['joints']) or True, send_cmd=lambda: None)
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=solve)
    node.delta_callback(Float64MultiArray(data=[1.] * 6))
    node.ctrl_loop()
    node.ctrl_loop()
    assert sent == [[2.] * 7, [4.] * 7]
    assert refs == [[0.] * 7, sent[0]]


def test_manual_speed_continues_past_twenty_steps_and_refreshes_without_a_gap(node, monkeypatch):
    import arm_delta_cmd.delta_ctrl_node as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    sent, calls = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[.5, 0., 0., 0., 0., 0.]))
    assert node.manual_velocity == [5., 0., 0., 0., 0., 0.]
    for i in range(35):
        now[0] = 100. + i / node.ctrl_rate
        node.ctrl_loop()
    assert len(sent) == len(calls) == 35
    assert all(c[0] == [.025, 0., 0.] for c in calls)
    assert node.have_goal and not node.traj_queue
    node.manual_delta_callback(Float64MultiArray(data=[-.5, 0., 0., 0., 0., 0.]))
    now[0] += .005
    node.ctrl_loop()
    assert calls[-1][0] == [-.025, 0., 0.]
    assert len(sent) == 36
    node.manual_delta_callback(Float64MultiArray(data=[0.] * 6))
    node.ctrl_loop()
    assert len(sent) == 36 and not node.have_goal
    assert node.manual_velocity == [0.] * 6


def test_manual_watchdog_uses_monotonic_time_and_does_not_resume(node, monkeypatch):
    import arm_delta_cmd.delta_ctrl_node as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    sent, _ = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[1.] * 6))
    node.ctrl_loop()
    # ROS clock still looks fresh; the manual watchdog must use steady elapsed time.
    now[0] += node.manual_timeout
    node.ctrl_loop()
    node.ctrl_loop()
    assert len(sent) == 1 and not node.have_goal
    assert node.manual_velocity == [0.] * 6


@pytest.mark.parametrize('bad', [[1.] * 5, [float('nan')] * 6, [float('inf')] * 6])
def test_invalid_manual_update_stops_previously_held_velocity(node, bad):
    sent, _ = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[1.] * 6))
    node.ctrl_loop()
    node.manual_delta_callback(Float64MultiArray(data=bad))
    node.ctrl_loop()
    assert len(sent) == 1 and not node.have_goal
    assert node.manual_velocity == [0.] * 6


def test_manual_speed_is_independent_of_delta_splits_and_uses_configured_rates(node):
    _, calls = install_fake_guard_robot(node)
    node.delta_splits = 1
    node.manual_command_rate = 20.
    node.ctrl_rate = 100.
    node.manual_delta_callback(Float64MultiArray(data=[1., 2., 3., 4., 5., 6.]))
    node.ctrl_loop()
    assert calls[0] == ([.2, .4, .6], [.8, 1., 1.2], 0)


def test_accepted_policy_command_replaces_manual_velocity_with_policy_hold(node):
    node.robot = SimpleNamespace(clear_set=lambda: None, set_joint_cmd_pose=lambda **kw: True,
                                 send_cmd=lambda: None)
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda q, *args: (True, list(q), None))
    node.manual_delta_callback(Float64MultiArray(data=[1.] * 6))
    assert node.have_goal and not node.traj_queue
    node.delta_callback(Float64MultiArray(data=[.2] * 6))
    assert node.queue_source == 'policy' and not node.traj_queue
    assert node.manual_velocity == [0.] * 6
    for _ in range(35):
        node.ctrl_loop()
    assert node.have_goal
    node.delta_callback(Float64MultiArray(data=[0.] * 6))
    assert not node.have_goal


@pytest.mark.parametrize('failure', ['ik', 'envelope', 'sdk', 'feedback'])
def test_manual_fault_cancels_velocity_hold(node, failure):
    sent, _ = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[1.] * 6))
    if failure == 'ik':
        node.tk.solve_tcp_delta_ik = lambda *a: (False, None, None)
    elif failure == 'envelope':
        node.tcp_anchor = [0.] * 3
        node.envelope_radius_mm = 1.
        node.kine = SimpleNamespace(fk=lambda _: [[1., 0., 0., 2.], [0., 1., 0., 0.],
                                                [0., 0., 1., 0.], [0., 0., 0., 1.]])
    elif failure == 'sdk':
        node.robot.set_joint_cmd_pose = lambda **kw: False
    else:
        node.cur_joints = [30.] * 7
        node.cmd_fb_err_strikes = 9
    node.ctrl_loop()
    count = len(sent)
    node.ctrl_loop()
    assert len(sent) == count and not node.have_goal
    assert node.manual_velocity == [0.] * 6


@pytest.mark.parametrize('parameter,value', [('manual_command_rate', '0.0'), ('manual_timeout', '-1.0')])
def test_invalid_manual_parameters_rejected(parameter, value):
    rclpy.init(args=['--ros-args', '-p', f'{parameter}:={value}'])
    try:
        with pytest.raises(ValueError, match=parameter):
            DeltaCtrlNode()
    finally:
        rclpy.shutdown()



def test_real_control_timer_keeps_sending_after_manual_twenty_steps(node):
    import time
    sent, _ = install_fake_guard_robot(node)
    node.manual_delta_callback(Float64MultiArray(data=[.1, 0., 0., 0., 0., 0.]))
    deadline = time.monotonic() + .18
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=.005)
    assert len(sent) > 20
    assert node.have_goal and not node.traj_queue
    node.manual_delta_callback(Float64MultiArray(data=[0.] * 6))
    count = len(sent)
    for _ in range(3):
        rclpy.spin_once(node, timeout_sec=.01)
    assert len(sent) == count


def test_policy_hold_uses_steady_watchdog_and_new_message_updates_speed(node, monkeypatch):
    import arm_delta_cmd.delta_ctrl_node as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    sent, calls = install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[.5, 0., 0., 0., 0., 0.]))
    for i in range(35):
        now[0] = 100. + i / node.ctrl_rate
        node.ctrl_loop()
    assert len(sent) == 35 and node.have_goal
    assert all(c[0] == [.025, 0., 0.] for c in calls)
    node.delta_callback(Float64MultiArray(data=[-.5, 0., 0., 0., 0., 0.]))
    node.ctrl_loop()
    assert calls[-1][0] == [-.025, 0., 0.]
    now[0] += node.delta_timeout
    node.ctrl_loop()
    assert not node.have_goal and node.policy_velocity == [0.] * 6
    assert len(sent) == 36


@pytest.mark.parametrize('bad', [[1.] * 5, [float('nan')] * 6, [float('inf')] * 6])
def test_invalid_policy_update_clears_hold_without_stopping_manual(node, bad):
    sent, _ = install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[1.] * 6))
    node.delta_callback(Float64MultiArray(data=bad))
    assert not node.have_goal and node.policy_velocity == [0.] * 6
    node.manual_delta_callback(Float64MultiArray(data=[1.] * 6))
    node.delta_callback(Float64MultiArray(data=bad))
    node.ctrl_loop()
    assert sent and node.queue_source == 'manual' and node.have_goal


def test_policy_speed_ignores_delta_splits_and_caps_retreat_at_nondefault_rate(node):
    import time
    _, calls = install_fake_guard_robot(node)
    node.delta_splits = 1
    node.policy_command_rate = 50.
    node.tactile_guard.update('a', [3., 0., 0., 0., 0., 0.], time.monotonic())
    node.ctrl_loop()
    node.delta_callback(Float64MultiArray(data=[-10., 0., 0., 0., 0., 0.]))
    node.ctrl_loop()
    assert node.queue_is_retreat
    assert abs(calls[-1][0][0]) * node.ctrl_rate <= node.tactile_retreat_speed_mm_s


def test_real_control_timer_keeps_sending_policy_past_twenty_steps(node):
    import time
    sent, _ = install_fake_guard_robot(node)
    node.delta_callback(Float64MultiArray(data=[.1, 0., 0., 0., 0., 0.]))
    deadline = time.monotonic() + .18
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=.005)
    assert len(sent) > 20 and node.have_goal
    node.delta_callback(Float64MultiArray(data=[0.] * 6))
    count = len(sent)
    for _ in range(3):
        rclpy.spin_once(node, timeout_sec=.01)
    assert len(sent) == count
