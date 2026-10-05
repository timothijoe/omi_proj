"""Deterministic protection tests: no ROS, SDK, hardware or command publishing."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ros2/arm_delta_cmd'))
from arm_delta_cmd.tactile_guard import TactileGuard


def armed():
    guard = TactileGuard(enabled=True)
    for i in range(20):
        for side in ('a', 'b'):
            guard.update(side, [0., 0., -3., 0., .2, 0.], i * .03)
    assert guard.capture_baseline(.57)[0]
    return guard


def test_startup_blocks_everything_until_explicit_baseline():
    guard = TactileGuard(enabled=True)
    assert guard.filter_action([1.] * 6, 0)[0] is None
    assert guard.filter_action([-1., 0., 0., 0., 0., 0.], 0)[0] is None
    assert not guard.capture_baseline(0)[0]


def test_normal_action_and_preload_are_preserved():
    guard = armed()
    action = [1., 2., 3., 4., 5., 6.]
    assert guard.filter_action(action, .58) == (tuple(action), 'clear')
    assert guard.metrics()['a']['delta_force'] == 0


@pytest.mark.parametrize('side', ['a', 'b'])
@pytest.mark.parametrize('component,delta', [(0, -2.), (1, 2.), (2, -2.),
                                           (3, .5), (4, -.5), (5, .5)])
def test_either_finger_any_sign_and_force_or_torque_trips(side, component, delta):
    guard = armed()
    values = [0., 0., -3., 0., .2, 0.]
    values[component] += delta
    guard.update(side, values, .58)
    assert guard.latched
    for action in ([1.] * 6, [0., 1., 0., 0., 0., 0.], [0.] * 6):
        assert guard.filter_action(action, .59)[0] is None
    assert guard.filter_action([-10., 100., 100., 100., 100., 100.], .59) == (
        (-.2, 0., 0., 0., 0., 0.), 'retreat_only')
    assert guard.filter_action([-.01, 1., 0., 0., 0., 0.], .59)[0][0] == -.01


def test_trip_is_latched_and_reset_requires_half_limit_without_rezero():
    guard = armed()
    base = dict(guard.baseline)
    guard.update('a', [3., 0., -3., 0., .2, 0.], .58)
    assert not guard.reset(.59)[0]
    guard.update('a', [1., 0., -3., 0., .2, 0.], .60)
    assert not guard.reset(.60)[0]  # equality at release threshold remains blocked
    guard.update('a', [0., 0., -3., 0., .2, 0.], .61)
    assert guard.filter_action([1.] * 6, .61)[0] is None
    assert not guard.capture_baseline(.61)[0]  # cannot absorb an overload into the baseline
    assert guard.reset(.61)[0]
    assert guard.baseline == base
    assert guard.filter_action([1.] * 6, .61)[1] == 'clear'


@pytest.mark.parametrize('values', [[float('nan')] * 6, [float('inf')] * 6, [0.] * 5])
def test_invalid_sensor_blocks_even_retreat(values):
    guard = armed()
    guard.update('b', values, .58)
    assert guard.filter_action([-1.] * 6, .59)[0] is None
    assert not guard.reset(.59)[0]


def test_staleness_blocks_retreat_and_recovery_needs_reset():
    guard = armed()
    assert guard.filter_action([-1.] * 6, .78)[0] is None
    for side in ('a', 'b'):
        guard.update(side, [0., 0., -3., 0., .2, 0.], .79)
    assert guard.filter_action([1.] * 6, .79)[0] is None
    assert guard.reset(.79)[0]


def test_unstable_or_old_baseline_rejected():
    guard = TactileGuard(enabled=True)
    for i in range(20):
        for side in ('a', 'b'):
            guard.update(side, [float(i % 2) * 2, 0., 0., 0., 0., 0.], i * .03)
    assert not guard.capture_baseline(.57)[0]
    assert not guard.capture_baseline(2.)[0]


def test_disabled_is_explicit_legacy_behavior_and_bad_limits_rejected():
    assert not TactileGuard().enabled
    assert TactileGuard(enabled=False).filter_action([1.] * 6, 0)[1] == 'disabled'
    for kwargs in ({'timeout': 0}, {'force_limit': float('nan')}, {'retreat_step_mm': -1}):
        with pytest.raises(ValueError):
            TactileGuard(**kwargs)
