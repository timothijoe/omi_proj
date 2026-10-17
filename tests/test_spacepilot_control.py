"""Robot command mapping and stop behavior without ROS, USB or SDK execution."""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hardware.spacepilot_pose import map_motion, SpaceNav
from omi_hil_rl.real.spacepilot_control import EnableGate, SpacePilotMapping, selected_action
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.real.receiver_preflight import validate_manual_motion


@pytest.mark.parametrize('field,index,sign', [
    ('z', 0, 1), ('x', 2, -1), ('y', 1, -1),
    ('rz', 3, 1), ('rx', 5, -1), ('ry', 4, -1),
])
def test_device_axes_to_receiver_wire(field, index, sign):
    event = NS(**dict.fromkeys(('x', 'y', 'z', 'rx', 'ry', 'rz'), 0))
    setattr(event, field, 350)
    action = SpacePilotMapping().action(map_motion(event))
    expected = np.zeros(6)
    expected[index] = sign  # 1 mm or 1 degree per 10 Hz command
    np.testing.assert_allclose(output_action(action, 'sdk-x-forward-z-left'), expected, atol=1e-12)


def test_independent_scales_norm_caps_and_rate():
    mapping = SpacePilotMapping(scale=2, translation_scale=.5, rotation_scale=.2, rate=20)
    action = mapping.action([350] * 6)
    assert np.linalg.norm(action[:3]) == pytest.approx(.01 / 20)
    assert np.linalg.norm(action[3:]) == pytest.approx(math.radians(4) / 20)
    np.testing.assert_allclose(action[:3] / np.linalg.norm(action[:3]), np.ones(3) / math.sqrt(3))
    assert not SpacePilotMapping(translation_scale=0).action([350]*6)[:3].any()
    assert not SpacePilotMapping(rotation_scale=0).action([350]*6)[3:].any()
    assert not SpacePilotMapping(scale=0).action([350]*6).any()


def test_deadzone_modes_signs_and_dominance():
    assert not SpacePilotMapping().action([18, -18, 0, 1, -1, 0]).any()
    assert not SpacePilotMapping(mode='translation').action([350]*6)[3:].any()
    assert not SpacePilotMapping(mode='rotation').action([350]*6)[:3].any()
    mapping = SpacePilotMapping(dominant=True, rotation_scale=0, signs=(-1, 1, 1, 1, 1, 1))
    action = mapping.action([100, 50, 0, 350, 0, 0])
    assert action[0] < 0 and np.count_nonzero(action) == 1
    with pytest.raises(ValueError):
        mapping.action([float('nan')]*6)


@pytest.mark.parametrize('kwargs', [
    {'translation_scale': -1}, {'rotation_scale': float('inf')}, {'scale': float('nan')},
    {'rate': 0}, {'deadzone': 350}, {'signs': (1,)*5},
])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        SpacePilotMapping(**kwargs)


def test_hold_toggle_disconnect_and_stale_input():
    gate, mapping = EnableGate(), SpacePilotMapping()
    driver = NS(connected=True, name='SpacePilot', raw=[350]*6, last_motion=1.)
    assert selected_action(driver, gate, mapping, 1.)[0] == 'idle'
    gate.on_button(19, True)
    assert selected_action(driver, gate, mapping, 1.1)[0] == 'human'
    assert selected_action(driver, gate, mapping, 1.16)[0] == 'stale'
    assert not selected_action(driver, gate, mapping, .9)[1].any()
    gate.on_button(19, False)
    assert not selected_action(driver, gate, mapping, 1.1)[1].any()
    gate.on_button(19, True)
    driver.connected = False
    assert selected_action(driver, gate, mapping, 1.1)[0] == 'disconnected'
    driver.connected = True
    assert selected_action(driver, gate, mapping, 1.1)[0] == 'idle'
    toggle = EnableGate(mode='toggle')
    toggle.on_button(19, True)
    toggle.on_button(19, True)  # repeated press does not toggle twice
    toggle.on_button(19, False)
    assert toggle.enabled
    toggle.on_button(19, True)
    assert not toggle.enabled
    toggle.on_button(12, True)
    assert not toggle.enabled


def test_driver_close_revokes_enable():
    gate = EnableGate(mode='toggle')
    gate.on_button(19, True)
    driver = SpaceNav(on_button=gate.on_button, on_reset=gate.reset)
    driver.close()
    assert not gate.enabled


def test_receiver_requires_matching_rate_and_base():
    rate, frame = NS(type=3, double_value=10.), NS(type=4, string_value='base')
    validate_manual_motion([rate, frame], 10.)
    with pytest.raises(ValueError, match='manual_command_rate'):
        validate_manual_motion([rate, frame], 20.)
    with pytest.raises(ValueError, match='delta_frame'):
        validate_manual_motion([rate, NS(type=4, string_value='tool')], 10.)


def load_script():
    path = Path(__file__).resolve().parents[1] / 'scripts/spacepilot_test.py'
    spec = importlib.util.spec_from_file_location('spacepilot_test_script', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reported_button_19_default_and_explicit_override():
    script = load_script()
    args = script.build_parser().parse_args([])
    assert args.enable_button == 19
    gate = EnableGate(args.enable_button)
    gate.on_button(14, True)
    assert not gate.enabled
    gate.on_button(19, True)
    assert gate.enabled
    gate.on_button(19, False)
    assert not gate.enabled
    custom = script.build_parser().parse_args(['--enable-button', '14'])
    gate = EnableGate(custom.enable_button)
    gate.on_button(19, True)
    assert not gate.enabled
    gate.on_button(14, True)
    assert gate.enabled
    gate.on_button(14, False)
    assert not gate.enabled


@pytest.mark.parametrize('ending', ['release', 'disconnect', 'error', 'stall'])
def test_publisher_stops_on_release_disconnect_error_and_stall(monkeypatch, ending):
    script = load_script()
    clock = NS(now=10.)
    messages, checks = [], []
    monkeypatch.setattr(script, 'time', NS(monotonic=lambda: clock.now,
                                         sleep=lambda dt: setattr(clock, 'now', clock.now+dt)))
    monkeypatch.setattr('builtins.input', lambda _: '')
    from omi_hil_rl.real import receiver_preflight

    def inspect(topic, **kwargs):
        checks.append(kwargs)
        return {'manual_topic': '/manual', 'policy_topic': '/policy'}

    monkeypatch.setattr(receiver_preflight, 'inspect_receiver', inspect)
    ros = NS(init=lambda **kw: None, ok=lambda: True, shutdown=lambda: None,
             spin_once=lambda *a, **kw: None)
    pub = NS(publish=lambda msg: messages.append((clock.now, msg.data)))
    node = NS(create_publisher=lambda *a: pub, count_publishers=lambda topic: int(topic == '/manual'),
              destroy_node=lambda: None)
    ros.create_node = lambda *a: node
    monkeypatch.setitem(sys.modules, 'rclpy', ros)
    monkeypatch.setitem(sys.modules, 'rclpy.signals', NS(SignalHandlerOptions=NS(NO=0)))
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', NS(Float64MultiArray=lambda data: NS(data=data)))

    class Driver:
        def __init__(self, on_button, on_reset):
            self.button, self.reset = on_button, on_reset
            self.connected, self.name = True, 'SpacePilot'
            self.message, self.last_button = self.name, ''
            self.last_motion, self.raw, self.count = clock.now, [350, 0, 0, 0, 0, 0], 0

        def poll(self, now):
            self.count += 1
            if self.count == 1:
                self.button(19, True)
                if ending == 'stall':
                    clock.now += .3
            elif self.count == 2:
                if ending == 'release':
                    self.button(19, False)
                elif ending == 'disconnect':
                    self.close()
                elif ending == 'error':
                    raise RuntimeError('injected input error')
            else:
                raise KeyboardInterrupt

        def close(self):
            self.reset()
            self.connected, self.name = False, ''

    monkeypatch.setattr(script, 'SpaceNav', Driver)
    args = script.build_parser().parse_args(['--execute'])
    with pytest.raises((KeyboardInterrupt, RuntimeError)):
        script.run(args, SpacePilotMapping(), EnableGate())
    assert checks == [{'require_connected': True, 'expected_manual_rate': 10.,
                       'allow_anonymous_subscriptions': True}]
    assert messages and not any(messages[-1][1])
    if ending != 'stall':
        assert messages[0][1] == [1., 0., 0., 0., 0., 0.]
        assert not any(messages[1][1])
        assert messages[1][0] - messages[0][0] < .1
    else:
        assert all(not any(data) for _, data in messages)


@pytest.mark.parametrize('stop_kind', ['release', 'neutral', 'stale'])
def test_start_immediate_then_10hz_and_immediate_restart(monkeypatch, stop_kind):
    script = load_script()
    clock = NS(now=10.)
    messages = []
    monkeypatch.setattr(script, 'time', NS(
        monotonic=lambda: clock.now,
        sleep=lambda dt: setattr(clock, 'now', round(clock.now + dt, 6))))
    monkeypatch.setattr('builtins.input', lambda _: '')
    from omi_hil_rl.real import receiver_preflight
    monkeypatch.setattr(receiver_preflight, 'inspect_receiver', lambda *a, **kw:
                        {'manual_topic': '/manual', 'policy_topic': '/policy'})
    pub = NS(publish=lambda msg: messages.append((clock.now, list(msg.data))))
    node = NS(create_publisher=lambda *a: pub,
              count_publishers=lambda topic: int(topic == '/manual'),
              destroy_node=lambda: None)
    monkeypatch.setitem(sys.modules, 'rclpy', NS(
        init=lambda **kw: None, ok=lambda: True, shutdown=lambda: None,
        spin_once=lambda *a, **kw: None, create_node=lambda *a: node))
    monkeypatch.setitem(sys.modules, 'rclpy.signals', NS(SignalHandlerOptions=NS(NO=0)))
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', NS(Float64MultiArray=lambda data: NS(data=data)))

    class Driver:
        def __init__(self, on_button, on_reset):
            self.button, self.reset = on_button, on_reset
            self.connected, self.name = True, 'SpacePilot'
            self.message, self.last_button = self.name, ''
            self.raw, self.last_motion, self.count = [0]*6, clock.now, 0

        def poll(self, now):
            self.count += 1
            if self.count == 30:
                raise KeyboardInterrupt
            self.last_motion = now
            # A direction change during continuous motion must not trigger an
            # extra publish, but the next scheduled message must use fresh data.
            self.raw = [350, 0, 0, 0, 0, 0] if self.count < 5 else [0, 350, 0, 0, 0, 0]
            if self.count in (2, 16):
                self.button(19, True)
            if self.count == 15:
                if stop_kind == 'release':
                    self.button(19, False)
                elif stop_kind == 'neutral':
                    self.raw = [0]*6
                else:
                    self.last_motion = now - 1.

        def close(self):
            self.reset()

    monkeypatch.setattr(script, 'SpaceNav', Driver)
    args = script.build_parser().parse_args(['--execute'])
    with pytest.raises(KeyboardInterrupt):
        script.run(args, SpacePilotMapping(), EnableGate())
    nonzero = [(stamp, data) for stamp, data in messages if any(data)]
    # Initial idle zero at 10.00 would previously delay first motion to 10.10.
    assert messages[0] == (10., [0.]*6)
    assert nonzero[0][0] == pytest.approx(10.01)
    assert nonzero[0][1] == pytest.approx([1, 0, 0, 0, 0, 0])
    assert nonzero[1][1] == pytest.approx([0, 0, 1, 0, 0, 0])
    assert any(stamp == pytest.approx(10.14) and not any(data) for stamp, data in messages)
    assert any(stamp == pytest.approx(10.15) for stamp, _ in nonzero)
    for segment in ([t for t, _ in nonzero if t < 10.14],
                    [t for t, _ in nonzero if t >= 10.15]):
        assert len(segment) == 2
        assert .1 - 1e-9 <= segment[1] - segment[0] <= .11 + 1e-9
    assert not any(messages[-1][1])
