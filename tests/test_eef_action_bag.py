import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.real.eef_action_bag import LABEL, decode_action, trajectory
from omi_hil_rl.training.eef_action import apply, between, from_rotvec


def test_round_trip_and_phase_endpoints():
    actions, phases = trajectory()
    assert actions.shape == (240, 6)
    assert phases[0] == "forward_x" and phases[-1] == "undo_forward_x"
    np.testing.assert_array_equal(actions[120:], -actions[:120][::-1])
    initial = np.r_[[.3, -.1, .6], from_rotvec([.2, -.3, .1])]
    current = initial.copy()
    for index, action in enumerate(actions):
        current = apply(current, action)
        if index == 19:
            np.testing.assert_allclose(current[:3], initial[:3] + [.05, 0, 0], atol=1e-14)
        if index == 39:
            np.testing.assert_allclose(current[:3], initial[:3] + [.05, -.05, 0], atol=1e-14)
        if index == 59:
            np.testing.assert_allclose(current[:3], initial[:3] + [.05, -.05, .05], atol=1e-14)
    np.testing.assert_allclose(between(initial, current), 0, atol=1e-14)
    assert math.isclose(actions[60:80, 3].sum(), math.radians(10))
    assert actions[0, 0] < actions[9, 0]  # Smooth start, not a 5cm jump.


@pytest.mark.parametrize("kwargs", [dict(hz=0), dict(seconds=float("nan")),
    dict(hz=10.1), dict(angle_deg=180), dict(distance=.5), dict(right_sign=0)])
def test_invalid_trajectory(kwargs):
    with pytest.raises(ValueError):
        trajectory(**kwargs)


def test_receiver_rejects_malformed_arrays():
    dim = NS(label=LABEL, size=6, stride=6)
    msg = NS(layout=NS(dim=[dim], data_offset=0), data=[.001, 0, 0, 0, 0, 0])
    np.testing.assert_array_equal(decode_action(msg), msg.data)
    for data in ([0]*7, [float("nan")]*6, [.051, 0, 0, 0, 0, 0]):
        msg.data = data
        with pytest.raises(ValueError):
            decode_action(msg)
    msg.data = [0]*6
    dim.label = "unknown"
    with pytest.raises(ValueError):
        decode_action(msg)
