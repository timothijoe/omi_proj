import argparse
from types import SimpleNamespace as NS

import pytest

from omi_hil_rl.real.gamepad_gripper import (
    BTN_A, BTN_B, GripperButtons, GamepadGripper,
    add_gripper_arguments, calibration_from_args,
)


def args(*extra):
    parser = argparse.ArgumentParser()
    add_gripper_arguments(parser)
    return parser.parse_args(list(extra))


def test_edges_release_conflict_and_reconnect():
    b = GripperButtons()
    released = {}
    a = {BTN_A: True}
    both = {**a, BTN_B: True}
    assert b.select(True, a) is None  # startup held button cannot move
    assert b.select(True, released) is None
    assert b.select(True, a) == 'close'
    assert b.select(True, a) is None
    b.select(True, released)
    assert b.select(True, both) is None
    assert b.select(True, a) is None  # conflict must release both
    b.select(True, released)
    assert b.select(True, {BTN_B: True}) == 'open'
    b.select(False, {})
    assert b.select(True, a) is None
    b.select(True, released)
    assert b.select(True, a) == 'close'  # RB is not required


@pytest.mark.parametrize('flag,value', [
    ('close-speed', '9'), ('close-speed', '101'), ('close-torque', '0'),
    ('close-torque', '101'), ('close-torque', 'nan'), ('close-position', '-1'),
    ('open-position', '1001'), ('close-position', '1.5'),
])
def test_parameter_ranges(flag, value):
    with pytest.raises(SystemExit):
        args('--gripper-' + flag, value)


class FakeSdk:
    def __init__(self, **kwargs):
        self.calls = [('connect', kwargs)]
        self.fail_send = False
        self.client = NS(send_can=lambda *a, **k: not self.fail_send)

    def grip_init_with_known_limits(self, **kwargs):
        self.calls.append(('init', kwargs))
        return True

    def set_speed(self, value):
        self.calls.append(('speed', value))
        return True

    def read_pos(self):
        return 500

    def set_torque_limit(self, value):
        self.calls.append(('torque', value))
        self.client.send_can(0x141, [])
        return True

    def move_to_pos(self, value):
        self.calls.append(('position', value))
        self.client.send_can(0x141, [])
        return True

    def close(self, **kwargs):
        self.calls.append(('close', kwargs))


def test_preview_never_constructs_sdk(capsys):
    a = args('--gripper-server', 'fake:55551')
    def factory(**kwargs):
        pytest.fail('Preview connected')
    g = GamepadGripper(a, {}, False, factory)
    g.start()
    g.tick(True, {})
    row = g.tick(True, {BTN_A: True})
    assert row == dict(action='close', position=0, speed=50, torque_percent=30, status='preview')
    g.close()


def test_sdk_parameters_order_default_torque_and_cleanup():
    a = args('--gripper-server', 'fake', '--gripper-close-position', '120',
             '--gripper-close-speed', '25')
    g = GamepadGripper(a, {}, True, FakeSdk)
    g.start()
    sdk = g.sdk
    try:
        g.tick(True, {})
        assert g.tick(True, {BTN_A: True})['status'] == 'submitted'
        g.pending.result(timeout=2)
        g.tick(True, {})
        g.tick(True, {BTN_B: True})
        g.pending.result(timeout=2)
        assert sdk.calls[2:] == [('speed', 25), ('torque', 30), ('position', 120),
                                 ('torque', 30), ('position', 1000)]
    finally:
        g.close()
    assert sdk.calls[-1] == ('close', {'reset_torque': False})


def test_transport_failure_prevents_position_and_surfaces_in_tick():
    g = GamepadGripper(args('--gripper-server', 'fake'), {}, True, FakeSdk)
    g.start()
    sdk = g.sdk
    try:
        sdk.fail_send = True
        g.tick(True, {})
        g.tick(True, {BTN_A: True})
        with pytest.raises(RuntimeError, match='CAN send'):
            g.pending.result(timeout=2)
        with pytest.raises(RuntimeError, match='CAN send'):
            g.tick(True, {})
        assert not any(k == 'position' for k, _ in sdk.calls)
    finally:
        g.close()


def test_busy_command_is_dropped_not_queued():
    g = GamepadGripper(args('--gripper-server', 'fake'), {}, True)
    g.pending = NS(done=lambda: False)
    g.tick(True, {})
    assert g.tick(True, {BTN_A: True})['status'] == 'busy_dropped'


def test_calibration_validation(tmp_path):
    parser = argparse.ArgumentParser()
    add_gripper_arguments(parser)
    p = tmp_path / 'limits.json'
    p.write_text('{"clamp_pos":100,"open_pos":-89900,"max_itinerary":90000,"speed_coe":3600}')
    a = parser.parse_args(['--gripper-server', 'fake', '--gripper-calibration', str(p)])
    assert calibration_from_args(a, parser)['max_itinerary'] == 90000
    p.write_text('{"clamp_pos":100,"open_pos":0,"max_itinerary":90000,"speed_coe":3600}')
    with pytest.raises(SystemExit):
        calibration_from_args(a, parser)
    a.gripper_calibration = None
    with pytest.raises(SystemExit):
        calibration_from_args(a, parser)


def test_init_failure_closes_without_resetting_torque():
    sdk = FakeSdk()
    sdk.grip_init_with_known_limits = lambda **kwargs: False
    g = GamepadGripper(args('--gripper-server', 'fake'), {}, True, lambda **kw: sdk)
    with pytest.raises(RuntimeError, match='initialization'):
        g.start()
    assert sdk.calls[-1] == ('close', {'reset_torque': False})


def test_custom_close_torque_and_feedback_fault():
    g = GamepadGripper(args('--gripper-server', 'fake', '--gripper-close-torque', '45'),
                       {}, True, FakeSdk)
    g.start()
    sdk = g.sdk
    try:
        g.tick(True, {})
        g.tick(True, {BTN_A: True})
        g.pending.result(timeout=2)
        assert sdk.calls[-2:] == [('torque', 45), ('position', 0)]
        g.tick(True, {})
        sdk.read_pos = lambda: -1
        g.tick(True, {BTN_B: True})
        with pytest.raises(RuntimeError, match='feedback'):
            g.pending.result(timeout=2)
        assert sdk.calls[-1] == ('position', 0)
    finally:
        g.close()
