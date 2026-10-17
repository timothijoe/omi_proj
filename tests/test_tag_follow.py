"""Robot-free checks of relative target geometry, inputs and ROS camera freshness."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from omi_hil_rl.real.tag_follow import (
    BTN_LB, BTN_START, BTN_SAVE, BTN_RB, FollowButtons, FollowController,
    R_MOUNT, load_calibration, load_default, save_default, transform,
)


def pose(xyz=(0, 0, 0), rot=(0, 0, 0)):
    t = np.eye(4)
    t[:3, :3] = cv2.Rodrigues(np.asarray(rot, dtype=float))[0]
    t[:3, 3] = xyz
    return t


def obs(b10=None, b12=None):
    return {10: NS(T=pose() if b10 is None else b10, rejected=False, side_px=100),
            12: NS(T=pose((0, 0, 1)) if b12 is None else b12, rejected=False, side_px=100)}


def controller():
    c = FollowController((pose(), pose()))
    c.observe(obs(), 1.)
    c.default = c.capture(1.)
    c.start(1.)
    return c


def test_capture_and_disk_roundtrip(tmp_path):
    c = controller()
    path = tmp_path / 'nested/default.json'
    save_default(path, c.default)
    np.testing.assert_allclose(load_default(path), pose((0, 0, 1)))
    save_default(path, pose((.2, 0, .9)))
    np.testing.assert_allclose(load_default(path), pose((.2, 0, .9)))
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('bad', [np.zeros((4, 4)), np.full((4, 4), np.nan), np.eye(3),
                               np.diag([-1, 1, 1, 1]), np.diag([2, 1, 1, 1])])
def test_invalid_transform(bad):
    with pytest.raises(ValueError):
        transform(bad)


def test_calibration_and_default_schema(tmp_path):
    path = tmp_path / 'data.json'
    path.write_text('{"T_base_cam": []}')
    with pytest.raises(KeyError):
        load_calibration(path)
    with pytest.raises(ValueError):
        load_default(path)


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('sign', [-1, 1])
def test_translation_error_and_mount(axis, sign):
    c = controller()
    delta = np.eye(3)[axis] * sign * .005
    c.observe(obs(b12=pose(np.array([0, 0, 1]) + delta)), 1.01)
    cmd = c.command(1.02)
    np.testing.assert_allclose(cmd[:3], R_MOUNT.T @ delta * 1000 * .08, atol=1e-10)
    np.testing.assert_allclose(cmd[3:], 0, atol=1e-10)


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('sign', [-1, 1])
def test_rotation_error_and_mount(axis, sign):
    c = controller()
    r = np.eye(3)[axis] * sign * np.radians(2)
    # Choose B12 so that restoring the relation asks for pure TCP rotation.
    c.observe(obs(b12=pose(rot=r) @ c.default), 1.01)
    cmd = c.command(1.02)
    np.testing.assert_allclose(cmd[:3], 0, atol=1e-10)
    np.testing.assert_allclose(cmd[3:], R_MOUNT.T @ np.degrees(r) * .08, atol=1e-10)


def test_nonidentity_calibration_offset_and_convergence():
    x = pose((.2, -.4, .1), (.3, -.1, .2))
    z = pose((.1, .03, -.04), (-.2, .1, .1))
    b10 = pose((.2, -.1, 1), (.2, .3, -.1))
    b12 = pose((-.1, .1, .8), (-.1, .5, .1))
    c = FollowController((x, z))
    c.observe(obs(b10, b12), 1.)
    c.default = c.capture(1.)
    c.start(1.)
    np.testing.assert_allclose(c.command(1.), 0, atol=1e-9)
    # Move target by a camera-frame rigid motion. Both translation and rotation
    # must be restored at the controlled TCP, including its tag lever arm.
    motion = pose((.01, -.02, .03), (.03, -.02, .01))
    c.observe(obs(b10, motion @ b12), 1.01)
    cmd = c.command(1.02)
    current = x @ b10 @ np.linalg.inv(z)
    desired = x @ motion @ b10 @ np.linalg.inv(z)
    expected_p = R_MOUNT.T @ (desired[:3, 3] - current[:3, 3]) * 1000
    expected_w = cv2.Rodrigues(R_MOUNT.T @ desired[:3, :3] @ current[:3, :3].T @ R_MOUNT)[0].ravel()
    np.testing.assert_allclose(c.error_mm_rotvec_deg, np.r_[expected_p, np.degrees(expected_w)])
    assert np.max(np.abs(cmd[:3])) <= .5
    assert np.max(np.abs(cmd[3:])) <= .2
    c.observe(obs(motion @ b10, motion @ b12), 1.03)
    np.testing.assert_allclose(c.command(1.04), 0, atol=1e-9)


def test_stale_rejected_missing_stop_and_reacquire():
    c = controller()
    moved = obs(b12=pose((.1, 0, 1)))
    c.observe(moved, 2.)
    assert np.any(c.command(2.01))
    np.testing.assert_array_equal(c.command(2.13), np.zeros(6))
    for invalid in ({10: moved[10]}, {}, {**moved, 10: NS(T=pose(), rejected=True, side_px=100)},
                    {**moved, 12: NS(T=pose(), rejected=False, side_px=19)}):
        c.observe(invalid, 3.)
        np.testing.assert_array_equal(c.command(3.01), np.zeros(6))
        with pytest.raises(ValueError):
            c.capture(3.01)
    c.observe(moved, 4.)
    assert np.any(c.command(4.01))
    c.stop()
    np.testing.assert_array_equal(c.command(4.02), np.zeros(6))
    assert c.default is not None


def test_no_default_or_calibration_cannot_start_but_can_capture():
    c = FollowController()
    c.observe(obs(), 1.)
    with pytest.raises(ValueError, match='default'):
        c.start(1.)
    c.default = c.capture(1.)
    with pytest.raises(ValueError, match='calibration'):
        c.start(1.)
    assert not c.active


def test_temporary_x_relation_does_not_replace_saved_default():
    c = controller()
    saved = c.default.copy()
    c.observe(obs(b12=pose((.1, 0, 1))), 1.01)
    c.start(1.01, temporary=c.capture(1.01))
    np.testing.assert_array_equal(c.command(1.02), np.zeros(6))
    np.testing.assert_array_equal(c.default, saved)
    c.stop()
    c.start(1.03)
    assert c.command(1.04)[0] == .5


def test_button_chords_edges_hold_release_and_reconnect():
    b = FollowButtons()
    assert b.select(True, {}) is None
    assert b.select(True, {BTN_START: True}) is None
    assert b.select(True, {BTN_START: True, BTN_LB: True}) is None
    assert b.select(True, {BTN_LB: True}) is None
    assert b.select(True, {BTN_SAVE: True, BTN_LB: True}) == 'save'
    assert b.select(True, {BTN_SAVE: True, BTN_LB: True}) is None
    assert b.select(True, {BTN_LB: True}) is None
    assert b.select(True, {BTN_START: True, BTN_LB: True}) == 'toggle'
    assert b.select(False, {}) == 'stop'
    assert b.select(True, {BTN_START: True, BTN_LB: True}) is None
    assert b.select(True, {BTN_START: True, BTN_LB: True}) is None
    assert b.select(True, {BTN_RB: True}) == 'stop'


def test_short_button_pulse_and_conflicting_buttons():
    b = FollowButtons()
    b.select(True, {})
    b.select(True, {BTN_LB: True})
    assert b.select(True, {BTN_LB: True}, [(304, True, False), (304, False, False)]) == 'toggle'
    assert b.select(True, {BTN_LB: True}, [(304, True, False), (305, True, False),
                                          (304, False, False), (305, False, False)]) is None
    assert b.select(True, {BTN_LB: True}, [(311, True, False), (311, False, False)]) == 'stop'


@pytest.fixture
def camera_module():
    path = Path(__file__).resolve().parents[1] / 'ros2/marker_detect/tag_follow_tag_v2.py'
    spec = importlib.util.spec_from_file_location('tag_follow_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def camera_fixture(module):
    camera = module.ROSCamera.__new__(module.ROSCamera)
    camera.node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=10_000_000_000)))
    camera.bridge = NS(imgmsg_to_cv2=lambda msg, desired_encoding: np.zeros((2, 3, 3), np.uint8))
    camera.info = camera.latest = camera.preview = None
    camera.sequence = 0
    camera.invalid_reason = ''
    header = NS(frame_id='color_optical', stamp=NS(sec=9, nanosec=990_000_000))
    info = NS(k=[100, 0, 1, 0, 100, 1, 0, 0, 1], d=[0]*5, width=3, height=2,
              distortion_model='plumb_bob', header=header)
    msg = NS(width=3, height=2, header=header)
    return camera, info, msg


def test_ros_image_intrinsics_and_invalid_frames(camera_module):
    camera, info, msg = camera_fixture(camera_module)
    camera.on_image(msg)
    assert camera.latest is None
    camera.on_info(info)
    camera.on_image(msg)
    assert camera.latest is not None
    assert camera.latest[1].shape == (2, 3, 3)
    np.testing.assert_array_equal(camera.latest[4], np.reshape(info.k, (3, 3)))
    msg.width = 4
    camera.on_image(msg)
    assert 'size/frame' in camera.invalid_reason
    info.distortion_model = 'equidistant'
    camera.on_info(info)
    assert camera.info is None


def test_receipt_clock_accepts_old_future_and_repeated_headers_but_expires(camera_module, monkeypatch):
    import omi_hil_rl.real.tag_follow_camera as camera_code
    now = [100.]
    monkeypatch.setattr(camera_code, 'time', NS(monotonic=lambda: now[0]))
    camera, info, msg = camera_fixture(camera_module)
    camera.node = NS(get_clock=lambda: pytest.fail('Following must not compare ROS/header clocks'))
    camera.on_info(info)
    for header_seconds in (0, 1, 1, 9999999999, 5):
        now[0] += .1
        msg.header.stamp.sec, msg.header.stamp.nanosec = header_seconds, 0
        camera.on_image(msg)
        assert camera.latest is not None and camera.invalid_reason == ''
        assert camera.latest[2] == header_seconds  # retained for calibration only
        assert camera.latest[3] == now[0]
    c = controller()
    c.observe(obs(b12=pose((.1, 0, 1))), camera.latest[3])
    assert np.any(c.command(now[0] + .01))
    np.testing.assert_array_equal(c.command(now[0] + .121), np.zeros(6))


def test_receipt_stamp_precedes_decode_so_processing_time_counts(camera_module, monkeypatch):
    import omi_hil_rl.real.tag_follow_camera as camera_code
    now = [100.]
    monkeypatch.setattr(camera_code, 'time', NS(monotonic=lambda: now[0]))
    camera, info, msg = camera_fixture(camera_module)
    camera.on_info(info)
    def slow_decode(*a, **kw):
        now[0] += .2
        return np.zeros((2, 3, 3), np.uint8)
    camera.bridge.imgmsg_to_cv2 = slow_decode
    camera.on_image(msg)
    assert camera.latest[3] == 100.
    c = controller()
    c.observe(obs(), camera.latest[3])
    assert not c.fresh(now[0])


def test_interrupted_gamepad_close_does_not_double_close(monkeypatch):
    from omi_hil_rl.real import linux_gamepad
    pad = linux_gamepad.LinuxGamepad()
    pad.fd = 123
    calls = []
    def interrupted_close(fd):
        calls.append(fd)
        raise KeyboardInterrupt
    monkeypatch.setattr(linux_gamepad.os, 'close', interrupted_close)
    with pytest.raises(KeyboardInterrupt):
        pad.close()
    pad.close()
    assert calls == [123] and pad.fd is None


def test_ros_default_topics(camera_module):
    args = camera_module.parser().parse_args([])
    assert args.image_topic == '/camera/camera/color/image_raw'
    assert args.camera_info_topic == '/camera/camera/color/camera_info'
    assert camera_module.CMD_TOPIC == '/omi/action/decision'


def test_runtime_publishes_follows_stops_on_dropout_and_cleanup(camera_module, monkeypatch, tmp_path):
    """Exercise main's ROS/gamepad loop without opening a device or publishing ROS."""
    import sys
    import json
    import omi_hil_rl.real.linux_gamepad as gamepad
    m = camera_module
    calibration_path = tmp_path / 'calibration.json'
    calibration_path.write_text(json.dumps({'X': pose().tolist(), 'Z': pose().tolist()}))
    default_path = tmp_path / 'default.json'
    published = []
    tick = [0]
    closed = []
    node = NS(create_publisher=lambda *a: NS(publish=lambda msg: published.append((tick[0], msg.data))),
              count_publishers=lambda topic: 1, destroy_node=lambda: closed.append('node'))
    ros = NS(init=lambda **kw: None, create_node=lambda name: node,
             ok=lambda: tick[0] < 9, shutdown=lambda: closed.append('ros'))
    monkeypatch.setitem(sys.modules, 'rclpy', ros)
    monkeypatch.setitem(sys.modules, 'rclpy.signals', NS(SignalHandlerOptions=NS(NO=0)))
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', NS(Float64MultiArray=lambda **kw: NS(**kw)))
    monkeypatch.setattr(m, 'time', NS(monotonic=lambda: tick[0] * .2 + 1))
    cameras = []

    class Camera:
        def __init__(self, *args):
            self.latest = None
            self.invalid_reason = ''
            cameras.append(self)

    def spin_once(*args, **kwargs):
        tick[0] += 1
        if tick[0] <= 4:
            cameras[0].latest = (tick[0], np.zeros((20, 20, 3), np.uint8), tick[0],
                                 m.time.monotonic(), np.eye(3), np.zeros(5), 'camera')
        # Ticks 5 onward: no new image. The last frame must expire.
        if tick[0] == 8:
            raise KeyboardInterrupt

    ros.spin_once = spin_once
    monkeypatch.setattr(m, 'ROSCamera', Camera)

    class Estimator:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, *args):
            assert args[1] == m.time.monotonic()  # receipt clock, not image header
            return obs(b12=pose((.1 if tick[0] >= 4 else 0, 0, 1)))

    monkeypatch.setitem(sys.modules, 'tag_pose', NS(TagPoseEstimator=Estimator,
                        STATIC_TAG_FILTER=None, MOVING_TAG_FILTER=None))

    class Pad:
        def __init__(self, device):
            self.error = ''
            self.button_events = []

        def poll(self):
            self.buttons = {BTN_LB: True}
            if tick[0] == 2:
                self.buttons[BTN_SAVE] = True
            if tick[0] == 4:
                self.buttons[BTN_START] = True
            return True

        def close(self):
            closed.append('pad')

    monkeypatch.setattr(gamepad, 'LinuxGamepad', Pad)
    m.main(['--headless', '--calibration', str(calibration_path), '--default-pose', str(default_path)])
    np.testing.assert_allclose(load_default(default_path), pose((0, 0, 1)))
    assert all(not any(data) for t, data in published if t < 4)
    assert any(any(data) for t, data in published if t == 4)
    assert all(not any(data) for t, data in published if t >= 5)
    assert published[-1] == (8, [0.] * 6)
    assert 'node' in closed and 'pad' in closed


def observe_sdk_error(c, translation_mm, rotation_deg, now=1.):
    desired = pose(R_MOUNT @ np.asarray(translation_mm) / 1000,
                   R_MOUNT @ np.radians(rotation_deg))
    c.observe(obs(b12=desired @ c.default), now)
    return c.command(now + .01)


def test_translation_deadband_stops_translation_while_rotation_corrects():
    c = controller()
    cmd = observe_sdk_error(c, [1., 0, 0], [0, 2., 0])
    np.testing.assert_array_equal(cmd[:3], np.zeros(3))
    assert cmd[4] == pytest.approx(.16)
    assert c.translation_holding and not c.rotation_holding
    # Diagnostics retain the real sub-deadband error, rather than hiding it.
    np.testing.assert_allclose(c.error_mm_rotvec_deg, [1., 0, 0, 0, 2., 0], atol=1e-8)


def test_rotation_deadband_stops_rotation_while_translation_corrects():
    c = controller()
    cmd = observe_sdk_error(c, [5., 0, 0], [0, .3, 0])
    assert cmd[0] == pytest.approx(.4)
    np.testing.assert_array_equal(cmd[3:], np.zeros(3))
    assert not c.translation_holding and c.rotation_holding


def test_independent_hysteresis_avoids_restart_inside_resume_bands():
    c = controller()
    np.testing.assert_array_equal(observe_sdk_error(c, [2., 0, 0], [.6, 0, 0]), np.zeros(6))
    assert c.state(1.01) == 'HOLDING'
    np.testing.assert_array_equal(observe_sdk_error(c, [3.2, 0, 0], [1., 0, 0]), np.zeros(6))
    cmd = observe_sdk_error(c, [3.6, 0, 0], [1., 0, 0])
    assert cmd[0] > 0 and not np.any(cmd[3:])
    cmd = observe_sdk_error(c, [2.4, 0, 0], [1.3, 0, 0])
    assert not np.any(cmd[:3]) and cmd[3] > 0
    np.testing.assert_array_equal(observe_sdk_error(c, [2., 0, 0], [.7, 0, 0]), np.zeros(6))
    assert c.state(1.01) == 'HOLDING'
    assert c.active  # Continues monitoring; a moved target can be followed again.
    assert c.state(1.2) == 'PAUSED'
    c.stop()
    assert c.state(1.01) == 'STOPPED'
    c.start(1.01)
    cmd = observe_sdk_error(c, [3., 0, 0], [1., 0, 0])
    assert cmd[0] > 0 and cmd[3] > 0  # A new start resets both hysteresis latches.


def test_deadband_is_vector_norm_and_combined_axis_commands_are_bounded():
    c = controller()
    cmd = observe_sdk_error(c, [2., 2., 0], [.6, .6, 0])
    assert np.any(cmd[:3]) and np.any(cmd[3:])
    cmd = observe_sdk_error(c, [100., -100., 100.], [30., -20., 25.])
    np.testing.assert_allclose(cmd[:3], [.5, -.5, .5], atol=1e-10)
    assert np.max(np.abs(cmd[3:])) <= .2


def simulate_delayed_follow(delay_ticks, retarget=False):
    """Ideal 10Hz BASE increment plant with delayed vision, not a robot model."""
    x = pose((.2, -.3, .7), (.2, -.1, .3))
    z = pose((-.3, .01, .06), (.15, -.1, -.2))
    b12 = pose((.2, .1, 1.2), (.1, .3, -.1))
    xinv = np.linalg.inv(x)
    default = np.linalg.inv(xinv @ z) @ b12
    c = FollowController((x, z), default)
    actual = pose(R_MOUNT @ np.array([.06, -.03, .08]),
                  R_MOUNT @ np.radians([8., -5., 4.]))
    target = np.eye(4)
    history = [(actual.copy(), target.copy())]
    commands, reached = [], []
    for tick in range(700 if retarget else 500):
        now = 1. + tick * .1
        if retarget and tick == 350:
            target = pose(R_MOUNT @ np.array([.02, -.015, .01]),
                          R_MOUNT @ np.radians([2., 1., -2.]))
        seen_a, seen_target = history[max(0, len(history)-1-delay_ticks)]
        seen_tag10 = xinv @ seen_a @ z
        # Small bounded observation noise at the camera/tag, including lever-arm effects.
        seen_tag10 = seen_tag10 @ pose(np.array([1., -.5, .4]) * .00005 * np.sin(tick),
                                       np.array([.5, 1., -.4]) * np.radians(.01) * np.cos(tick))
        c.observe(obs(seen_tag10, xinv @ seen_target @ z @ default), now)
        if tick == 0: c.start(now)
        wire = c.command(now + .01)
        commands.append(wire)
        a, b, cc = np.radians(wire[3:])
        rdelta = pose(rot=(0., 0., cc))[:3, :3] @ pose(rot=(0., b, 0.))[:3, :3] @ pose(rot=(a, 0., 0.))[:3, :3]
        actual[:3, 3] += R_MOUNT @ wire[:3] / 1000
        actual[:3, :3] = R_MOUNT @ rdelta @ R_MOUNT.T @ actual[:3, :3]
        history.append((actual.copy(), target.copy()))
        reached.append(c.state(now + .01) == 'HOLDING')
    pos_error = np.linalg.norm(actual[:3, 3] - target[:3, 3]) * 1000
    rot_error = np.degrees(np.linalg.norm(cv2.Rodrigues(target[:3, :3] @ actual[:3, :3].T)[0]))
    return np.asarray(commands), np.asarray(reached), pos_error, rot_error


@pytest.mark.parametrize('delay_ticks', [0, 4, 6, 8])
def test_delayed_feedback_converges_to_zero_command(delay_ticks):
    commands, reached, mm, deg = simulate_delayed_follow(delay_ticks)
    assert np.max(np.abs(commands[:, :3])) <= .5
    assert np.max(np.abs(commands[:, 3:])) <= .2
    assert np.all(commands[-50:] == 0), (mm, deg)
    assert reached[-50:].all()
    assert mm <= 3.5 and deg <= 1.2


def test_holding_restarts_for_moved_target_then_settles_again():
    commands, reached, mm, deg = simulate_delayed_follow(6, retarget=True)
    assert reached[300:350].all()
    assert np.any(commands[360:400])
    assert np.all(commands[-50:] == 0)
    assert reached[-50:].all()
    assert mm <= 3.5 and deg <= 1.2
