import json
import math
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.real.gamepad_home import BTN_X, GamepadHome, HomeSteps, pose_delta
from omi_hil_rl.real.sdk_action import rotvec_to_sdk_abc


def poses(distance=.0025, angle=.025):
    current, target = np.eye(4), np.eye(4)
    target[:3, 3] = [distance, 0, 0]
    target[:3, :3] = [[math.cos(angle), -math.sin(angle), 0],
                       [math.sin(angle), math.cos(angle), 0], [0, 0, 1]]
    return current, target


def test_steps_sum_to_full_pose_delta_and_do_not_overshoot():
    current, target = poses()
    plan = HomeSteps(current, target)
    steps = []
    while not plan.done:
        steps.append(plan.step())
    assert len(steps) == 3
    assert np.sum(steps, axis=0) == pytest.approx(pose_delta(current, target))
    assert all(np.linalg.norm(s[:3]) <= .001+1e-12 for s in steps)
    assert all(np.linalg.norm(s[3:]) <= math.radians(1)+1e-12 for s in steps)
    assert steps[-1][0] == pytest.approx(.0005)


@pytest.mark.parametrize('angle', [0., 1e-9, math.pi, math.pi-1e-7, -.4])
def test_zero_translation_and_rotation_edge_cases(angle):
    current, target = poses(0., angle)
    delta = pose_delta(current, target)
    assert abs(delta[5]) == pytest.approx(abs(angle), abs=1e-7)
    plan = HomeSteps(current, target)
    for _ in range(200):
        if plan.done:
            break
        assert np.isfinite(plan.step()).all()
    assert plan.done


def controller():
    now = [0.]
    home = GamepadHome(clock=lambda: now[0])
    requests = []
    def request(_):
        future = Future()
        requests.append(future)
        return future
    home.client = SimpleNamespace(service_is_ready=lambda: True, call_async=request)
    home.request_type = lambda: None
    home.tick(True, {311: True})
    return home, now, requests


def resolve(future, current=None, target=None):
    if current is None:
        current, target = poses()
    future.set_result(SimpleNamespace(success=True, message=json.dumps(
        dict(frame='sdk_base', current=current.tolist(), target=target.tolist()))))


def test_press_once_10hz_and_exact_sdk_base_wire():
    home, now, requests = controller()
    buttons = {311: True, BTN_X: True}
    assert home.tick(True, buttons)[0] == 'home_waiting'
    resolve(requests[0])
    mode, delta, data = home.tick(True, buttons)
    assert mode == 'human_home'
    assert data[:3] == pytest.approx(delta[:3]*1000)
    assert data[3:] == pytest.approx(rotvec_to_sdk_abc(delta[3:]))
    now[0] = .05
    assert home.tick(True, buttons)[2] == [0.]*6
    now[0] = .1
    assert home.tick(True, buttons)[2][0] == pytest.approx(1.)
    now[0] = .2
    assert home.tick(True, buttons)[2][0] == pytest.approx(.5)
    assert home.tick(True, buttons) is None
    assert len(requests) == 1


@pytest.mark.parametrize('connected,buttons', [(True, {BTN_X: True}), (False, {})])
def test_release_or_disconnect_cancels_request_and_motion(connected, buttons):
    home, now, requests = controller()
    home.tick(True, {311: True, BTN_X: True})
    assert home.tick(connected, buttons) is None
    assert requests[0].cancelled()
    assert home.future is home.plan is None
    home, now, requests = controller()
    home.tick(True, {311: True, BTN_X: True})
    resolve(requests[0])
    home.tick(True, {311: True, BTN_X: True})
    home.tick(connected, buttons)
    assert home.plan is None


def test_timeout_failed_fk_and_unavailable_service_send_zero():
    home, now, requests = controller()
    buttons = {311: True, BTN_X: True}
    home.tick(True, buttons)
    now[0] = 1.1
    assert home.tick(True, buttons)[2] == [0.]*6
    assert requests[0].cancelled()
    home.tick(True, {311: True})
    home.tick(True, buttons)
    requests[-1].set_result(SimpleNamespace(success=False, message='FK failed'))
    assert home.tick(True, buttons)[0] == 'home_failed'
    home.tick(True, {311: True})
    home.client = None
    assert home.tick(True, buttons)[0] == 'home_unavailable'


def test_x_pressed_without_rb_does_not_start_on_rb_press():
    home, _, requests = controller()
    home.tick(True, {BTN_X: True})
    home.tick(True, {311: True, BTN_X: True})
    assert not requests


def test_standard_physical_x_308_triggers_and_north_307_does_not():
    home, _, requests = controller()
    assert home.tick(True, {311: True, 307: True}) is None
    assert not requests
    assert home.tick(True, {311: True, 308: True})[0] == 'home_waiting'
    assert len(requests) == 1


def test_legacy_physical_x_code_can_be_configured():
    home, _, requests = controller()
    home.button_code = 307
    assert home.tick(True, {311: True, 308: True}) is None
    assert home.tick(True, {311: True, 307: True})[0] == 'home_waiting'
    assert len(requests) == 1


def test_314_alone_starts_home_and_rb_release_does_not_cancel():
    home, now, requests = controller()
    home.button_code = 314
    home.require_rb = False
    home.tick(True, {})
    assert home.tick(True, {314: True})[0] == 'home_waiting'
    resolve(requests[0])
    assert home.tick(True, {314: True, 311: True})[0] == 'human_home'
    now[0] = .1
    assert home.tick(True, {})[0] == 'human_home'
    assert not requests[0].cancelled()
    assert len(requests) == 1


def test_314_alone_disconnect_cancels_home():
    home, _, requests = controller()
    home.button_code = 314
    home.require_rb = False
    home.tick(True, {})
    assert home.tick(True, {314: True})[0] == 'home_waiting'
    assert home.tick(False, {}) is None
    assert requests[0].cancelled()
    assert home.future is home.plan is None


def test_314_press_and_release_in_one_poll_starts_home_once():
    home, _, requests = controller()
    home.button_code = 314
    home.require_rb = False
    home.tick(True, {})
    transitions = [(314, True, False), (314, False, False)]
    assert home.tick(True, {}, transitions)[0] == 'home_waiting'
    assert len(requests) == 1
    home.tick(True, {})
    assert len(requests) == 1


def test_invalid_fk_rejected():
    current, target = poses()
    target[0, 0] = 5
    with pytest.raises(ValueError, match='rotation'):
        HomeSteps(current, target)
