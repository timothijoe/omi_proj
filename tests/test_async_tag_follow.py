"""Training/follow arbitration and replay isolation, without ROS or devices."""
from concurrent.futures import Future
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.real.tag_follow import (FollowButtonFilter, FollowButtons, FollowController,
                                      load_default, save_default)
from omi_hil_rl.real.tag_follow_session import TagFollowSession
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.hil.ros_transport import RosTransport
from omi_hil_rl.hil.periodic_control import observation_action, run_periodic
from omi_hil_rl.hil.periodic_replay import eligibility
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport


def poses(offset=0.):
    t10, t12 = np.eye(4), np.eye(4)
    t12[:3, 3] = [offset, 0, 1]
    return {10: NS(T=t10, side_px=100, rejected=False),
            12: NS(T=t12, side_px=100, rejected=False)}


def session(path, now):
    s = TagFollowSession.__new__(TagFollowSession)
    s.controller = FollowController((np.eye(4), np.eye(4)))
    s.controller.observe(poses(), now)
    s.controller.default = s.controller.capture(now)
    s.controller.observe(poses(.01), now)
    s.buttons, s.button_filter = FollowButtons(), FollowButtonFilter()
    s.camera = s.pool = s.pending = None
    s.default_path, s.error = path, ''
    s.next_command = s.next_log = 0.
    return s


def transport(tmp_path, now):
    tr = RosTransport.__new__(RosTransport)
    tr.tag_follow = session(tmp_path/'default.json', now[0])
    tr.node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=int(now[0]*1e9))))
    tr.connected, tr.events = True, set()
    tr.pad = NS(buttons={}, axes={}, button_events=[])
    tr.home = None
    tr.invalidated = []
    tr.policy_pipeline = NS(invalidate=lambda: tr.invalidated.append(True))
    tr.sent = []
    tr._publish = lambda a, **kw: tr.sent.append((a.copy(), kw))
    def stop():
        tr._cancel_tag_follow()
        tr.sent.append((np.zeros(6), {'source': 'stop'}))
    tr.stop = stop
    return tr


def test_lb_chords_are_reserved_until_release_even_when_lb_released_first():
    f = FollowButtonFilter()
    f.gripper_input({}, [])
    buttons, events = f.gripper_input({310: True, 304: True},
                                     [(310, True, False), (304, True, False)])
    assert not buttons.get(304) and not any(e[0] == 304 for e in events)
    buttons, events = f.gripper_input({304: True}, [(310, False, False)])
    assert not buttons.get(304)
    f.gripper_input({}, [(304, False, False)])
    buttons, events = f.gripper_input({304: True}, [(304, True, False)])
    assert buttons[304] and events == [(304, True, False)]
    # A whole LB+B pulse within one kernel read must not open the gripper.
    f = FollowButtonFilter()
    _, events = f.gripper_input({}, [(310, True, False), (305, True, False),
                                     (305, False, False), (310, False, False)])
    assert not any(e[0] == 305 for e in events)


def test_actor_save_start_sdk_route_and_rb_cancel(tmp_path, monkeypatch):
    import omi_hil_rl.hil.ros_transport as module
    now = [1.]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: now[0]))
    tr = transport(tmp_path, now)
    tr._tag_follow_input([])
    tr.pad.buttons = {310: True, 305: True}
    tr._tag_follow_input([])
    np.testing.assert_allclose(load_default(tr.tag_follow.default_path)[:3, 3], [.01, 0, 1])
    assert not tr.tag_follow.active
    tr.pad.buttons = {310: True}
    tr._tag_follow_input([])
    tr.tag_follow.controller.observe(poses(.02), now[0])
    tr.pad.buttons[304] = True
    tr._tag_follow_input([])
    assert tr.tag_follow.active
    assert tr.invalidated and tr._tag_follow_resume_after == 1_000_000_000
    assert tr._tag_follow_tick()
    action, kwargs = tr.sent[-1]
    assert kwargs == dict(convention='sdk-base-aligned', source='tag_follow')
    np.testing.assert_allclose(output_action(action, kwargs['convention']),
                               tr.tag_follow.controller.command(now[0]), atol=1e-10)
    count = len(tr.sent)
    assert tr._tag_follow_tick() and len(tr.sent) == count  # 10Hz, no burst
    now[0] += .13
    tr._tag_follow_tick()
    np.testing.assert_array_equal(tr.sent[-1][0], np.zeros(6))  # frame expired
    tr.pad.buttons = {311: True}
    tr._tag_follow_input([])
    assert not tr.tag_follow.active
    assert tr.tag_follow_epoch >= 3


@pytest.mark.parametrize('kind', ['disconnect', 'home', 'start', 'manual_stop', 'success', 'drain'])
def test_other_controls_stop_follow_without_restart(tmp_path, monkeypatch, kind):
    import omi_hil_rl.hil.ros_transport as module
    now = [1.]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: now[0]))
    tr = transport(tmp_path, now)
    tr._tag_follow_input([])
    tr.tag_follow.controller.start(1.)
    if kind == 'disconnect':
        tr.connected = False
    elif kind == 'home':
        tr.home = NS(future=None, plan=None, button_code=314)
        tr.pad.buttons[314] = True
    elif kind == 'drain':
        tr.tag_follow_inhibit = True
    else:
        tr.events.add(kind)
    tr._tag_follow_input([])
    assert not tr.tag_follow.active
    assert not np.any(tr.sent[-1][0])


def test_policy_selection_waits_for_post_follow_observation():
    takes = []
    tr = NS(latest=({}, 100), tag_follow=NS(active=True),
            policy_pipeline=NS(take=lambda: takes.append(1)),
            _tag_follow_resume_after=100)
    assert observation_action(tr, None, {'policy': True, 'human': True}) is None
    tr.tag_follow.active = False
    assert observation_action(tr, None, {'policy': True, 'human': True}) is None
    assert takes == []


@pytest.mark.parametrize('timing', ['strict', 'diagnostic_only_v1'])
def test_replay_never_bridges_a_follow_reset(timing):
    before = dict(observation_present=True, control_epoch=0)
    after = dict(observation_present=True, control_epoch=2)
    assert eligibility(before, after, [], [], timing_policy=timing) == 'tag_follow_boundary'


def test_detection_future_never_blocks_controls_or_revives_invalid_camera(tmp_path):
    s = session(tmp_path/'default.json', 1.)
    s.pending = Future()
    s.camera = NS(latest=None, invalid_reason='camera disconnected')
    s.refresh()  # Would block if this called .result() on unfinished work.
    assert s.controller.pair is None
    s.pending.set_result((poses(), 1.))
    s.refresh()
    assert s.controller.pair is None and s.controller.reason == 'camera disconnected'


def test_periodic_follow_pauses_clock_and_is_excluded_from_training(tmp_path, monkeypatch):
    import omi_hil_rl.hil.periodic_control as periodic
    import omi_hil_rl.hil.ros_transport as ros
    now = [100.]
    clock = NS(monotonic=lambda: now[0])
    monkeypatch.setattr(periodic, 'time', clock)
    monkeypatch.setattr(ros, 'time', clock)
    config = HILConfig(transport='ros', review='auto', wrist_camera='required', episode_seconds=1.)
    obs = FakeTransport()._observation()
    obs['history_mask'][:] = 1
    obs['camera_mask'][:] = 1
    pending, sent, follows = [], [], []

    class Transport:
        _tag_follow_input = RosTransport._tag_follow_input
        _tag_follow_tick = RosTransport._tag_follow_tick
        _cancel_tag_follow = RosTransport._cancel_tag_follow
        _invalidate_tag_follow_policy = RosTransport._invalidate_tag_follow_policy

        def __init__(self):
            self.config, self.connected, self.arbitration_mode = config, True, 'after-inference'
            self.pad = NS(buttons={}, axes={})
            self.events, self.event_times = set(), {}
            self.node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=int(now[0]*1e9))))
            self.latest = self.consumed = None
            self.policy_pipeline = NS(take=self.take, invalidate=self.invalidate)
            self.tag_follow = session(tmp_path/'default.json', now[0])
            self.tag_follow.buttons.select(True, {})
            self.tag_follow.command = lambda t: self.tag_follow.controller.action(t)
            self.home = None
            self._next_toggle = 0

        def invalidate(self):
            self.consumed = self.latest[1] if self.latest else None

        def take(self):
            if self.latest[1] == self.consumed:
                return None
            self.consumed = self.latest[1]
            return (*self.latest, np.ones(6)*.1, 5.)

        def wait_start(self): return now[0]
        def start_episode(self): pass
        def idle_tick(self): pass
        def stop(self): self._cancel_tag_follow()

        def _pump(self):
            now[0] += .01
            stamp = round(int(now[0]*10) * 1e8)
            self.latest = (obs, stamp)
            self.latest_eef_time = stamp
            self.observation_hook(stamp, self.latest, {})
            self.tag_follow.controller.observe(poses(.01), now[0])
            self.pad.buttons = {310: True}
            if self._next_toggle == 0 and now[0] >= 100.35:
                self.pad.buttons[304] = True
                self._next_toggle = 1
            elif self._next_toggle == 1 and now[0] >= 100.75:
                self.pad.buttons[304] = True
                self._next_toggle = 2
            self._tag_follow_input([])
            for deadline, receipt in list(pending):
                if now[0] >= deadline:
                    pending.remove((deadline, receipt))
                    if self.receipt_hook:
                        self.receipt_hook(receipt)

        def _publish(self, action, command_id=None, **kwargs):
            if kwargs.get('source') == 'tag_follow':
                follows.append(now[0])
                assert command_id is None
                return output_action(action, kwargs['convention'])
            wire = output_action(action, config.sdk_convention)
            sent.append((now[0], command_id, self.tag_follow_epoch if hasattr(self, 'tag_follow_epoch') else 0))
            self.last_command_trace = {}
            pending.append((now[0]+.001, dict(command_id=command_id, accepted=True, finished=False,
                status='queue_accepted', control_mode='velocity_hold', arm='A', delta_frame='base',
                nominal_duration_s=.1, action_source=self.last_owner, wire_action=wire,
                timestamp_ns=int((now[0]+.001)*1e9))))
            return wire

    tr = Transport()
    actor = NS(transport=tr, config=config, run=tmp_path, version=1, policy=True,
               load=lambda: None, close_pipeline=lambda: None, state=lambda *a, **kw: None,
               finished=lambda *a: None)
    run_periodic(actor, 1, training=True)
    audit = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert audit['reason'] == 'timeout'
    assert audit['tag_follow_paused_seconds'] == pytest.approx(.4, abs=.03)
    assert follows and all(not 100.35 <= t < 100.75 for t, _, _ in sent)
    assert any(t > 101.2 for t, _, _ in sent)  # the one-second clock paused
    assert audit['excluded']['tag_follow_boundary'] >= 1
    assert audit['training_ready']
    assert {epoch for _, _, epoch in sent} == {0, 2}


def test_real_pump_suppresses_gripper_and_policy_until_fresh_resume(tmp_path, monkeypatch):
    import omi_hil_rl.hil.ros_transport as module
    from omi_hil_rl.hil.environment import ButtonEvents
    from omi_hil_rl.real.gamepad_gripper import GripperButtons
    now = [1.]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: now[0]))
    tr = transport(tmp_path, now)
    tr.config = HILConfig(transport='ros', review='auto')
    tr.buttons = ButtonEvents(tr.config)
    tr.event_times = {}
    tr.rclpy = NS(ok=lambda: True, spin_once=lambda *a, **kw: None)
    tr.pad.poll = lambda: True
    tr.next_reference = tr.latest = None
    tr.observation_driven, tr.arbitration_mode = True, 'after-inference'
    tr.runtime = NS(window=lambda stamp: (({}, np.ones(10)),
                    dict(source_receive_ns={'eef': stamp})))
    offered, grip = [], []
    tr.policy_pipeline.check = lambda: None
    tr.policy_pipeline.offer = lambda obs, stamp: offered.append(stamp)
    selector = GripperButtons()
    tr.gripper = NS(tick=lambda connected, buttons, events:
                    grip.append(selector.select(connected, buttons, events)))
    tr._pump()
    now[0] = 1.01
    tr.pad.buttons = {310: True, 305: True}
    tr._pump()
    now[0] = 1.02
    tr.pad.buttons = {310: True}
    tr._pump()
    now[0] = 1.03
    tr.pad.buttons[304] = True
    tr._pump()
    assert tr.tag_follow.active
    assert offered == [1_000_000_000]
    now[0] = 1.04
    tr.pad.buttons = {311: True}
    tr._pump()
    assert not tr.tag_follow.active
    assert offered == [1_000_000_000]
    now[0] = 1.11
    tr.pad.buttons = {}
    tr._pump()
    assert offered[-1] == 1_100_000_000
    assert all(command is None for command in grip)
    tr.pad.buttons = {304: True}
    tr._pump()
    assert grip[-1] == 'close'


def test_background_detector_uses_receipt_clock_not_header(tmp_path):
    s = session(tmp_path/'default.json', 1.)
    initialized, stamps = [], []
    class Estimator:
        def __init__(self, *a, **kw): initialized.append(True)
        def process(self, gray, stamp):
            stamps.append(stamp)
            return poses()
    s.detector = NS(TagPoseEstimator=Estimator, MOVING_TAG_FILTER=None, STATIC_TAG_FILTER=None)
    s.signature, s.last_stamp = None, float('-inf')
    for i, header in enumerate((9999., 0., 0.)):
        frame = (i, np.zeros((20, 20, 3), np.uint8), header, 100.+i*.1,
                 np.eye(3), np.zeros(5), 'camera')
        observations, received = s._detect(frame)
        assert received == 100.+i*.1
    assert len(initialized) == 1
    assert stamps == [100., 100.1, 100.2]
