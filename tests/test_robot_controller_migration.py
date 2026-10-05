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
                     '-p', 'enable_publish_joint_state:=false'])
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


def test_fake_ik_preserves_vendor_splitting_and_command_anchor(node):
    calls = []

    def solve(q, translation, abc, frame):
        calls.append((list(q), translation, abc, frame))
        return True, [v + 0.1 for v in q], None

    node.robot = object()
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=solve)
    node.cur_joints = [4.0] * 7
    node.delta_callback(Float64MultiArray(data=[2., 4., 6., 8., 10., 12.]))
    assert len(calls) == len(node.traj_queue) == 20
    assert calls[0] == ([4.] * 7, [0.1, 0.2, 0.3], [0.4, 0.5, 0.6], 0)
    assert node.traj_queue[-1] == pytest.approx([6.] * 7)
    node.delta_callback(Float64MultiArray(data=[0.] * 6))
    assert len(node.traj_queue) == 20  # replacement, not append


def test_nonfinite_command_never_reaches_ik(node):
    node.robot = object()
    node.kine = object()
    node.tk = SimpleNamespace(solve_tcp_delta_ik=lambda *a: pytest.fail('IK called'))
    node.delta_callback(Float64MultiArray(data=[float('nan')] + [0.] * 5))
    assert not node.traj_queue


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
