"""Start uses live sensor history without carrying an old action into a round."""
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import ButtonEvents, InteractionUnavailable, RealHILEnv
from omi_hil_rl.hil.ros_transport import RosTransport
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.stack_shadow import StackObservations


@pytest.fixture
def live_transport(monkeypatch):
    clock = [1_000_000_000]
    config = HILConfig(transport='ros', wrist_camera='required', episode_seconds=2.)
    tr = RosTransport.__new__(RosTransport)
    tr.config = config
    tr.runtime = StackObservations(GridProfile('required').CONTRACT)
    tr.runtime.profile.decode = lambda key, message: (message.stamp, message.value)
    tr.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=clock[0])))
    tr.pad = SimpleNamespace(buttons={}, poll=lambda: True)
    tr.buttons = ButtonEvents(config)
    tr.events, tr.event_times = set(), {}
    tr.next_reference = tr.latest = None
    tr.home = tr.publisher = None
    tr.last_owner = None
    tr.connected = True
    tr.stop = lambda: None
    candidates = {}
    tr.policy_pipeline = SimpleNamespace(
        invalidate=candidates.clear,
        check=lambda: None,
        offer=lambda observation, stamp: candidates.update({stamp: (np.zeros(6), 0.)}),
        get=candidates.get)
    streaming = [True]

    def spin_once(node, timeout_sec):
        clock[0] += 5_000_000
        if not streaming[0]:
            return
        for key in tr.runtime.topics.values():
            if key in ('rgb', 'wrist_rgb'):
                value = np.full((3, 128, 128), (clock[0] // 100_000_000) % 256, np.uint8)
            elif key == 'eef':
                value = np.array([.5, .1, .8, 0, 0, 0, 1], np.float32)
            else:
                value = np.zeros((1 if key.endswith('depth') else 2, 16, 24), np.float32)
            tr.runtime.ingest(key, SimpleNamespace(stamp=clock[0], value=value), clock[0])

    tr.rclpy = SimpleNamespace(ok=lambda: True, spin_once=spin_once)
    monkeypatch.setattr('omi_hil_rl.hil.ros_transport.time',
                        SimpleNamespace(monotonic=lambda: clock[0] / 1e9))
    return tr, clock, streaming


def prime(tr, clock, frames):
    for _ in range(frames):
        if tr.next_reference is not None:
            clock[0] = tr.next_reference - 5_000_000
        tr._pump()


def test_start_keeps_ten_real_frames_and_held_button_keeps_rolling(live_transport):
    tr, clock, _ = live_transport
    prime(tr, clock, 10)
    before, stamp = tr.latest
    history = tuple(tr.runtime.history)
    epoch = tr.runtime.epoch
    tr.pad.buttons[tr.config.start_button] = True
    started = clock[0]
    env = RealHILEnv(tr, tr.config, clock=lambda: clock[0] / 1e9)
    observation, info = env.reset()
    assert clock[0] - started < 100_000_000
    assert info['deadline'] == info['started'] + 2.
    assert observation is before and env.previous_stamp == stamp
    assert tuple(tr.runtime.history) == history and tr.runtime.epoch == epoch
    assert np.all(observation['history_mask'] == 1)
    assert len(np.unique(observation['rgb'][:, 0, 0, 0])) == 10
    prime(tr, clock, 12)  # Holding Start never triggers repeated starts/resets.
    assert 'start' not in tr.events
    assert tr.runtime.epoch == epoch and len(tr.runtime.history) == 10
    assert tr.latest[1] > stamp and tr.latest[0]['history_mask'].all()


def test_episode_invalidates_previous_action_but_preserves_history(live_transport):
    tr, clock, _ = live_transport
    prime(tr, clock, 10)
    latest, next_reference, epoch = tr.latest, tr.next_reference, tr.runtime.epoch
    assert tr.policy_pipeline.get(latest[1]) is not None
    tr.start_episode()
    assert tr.policy_pipeline.get(latest[1]) is None
    assert tr.latest is latest and tr.next_reference == next_reference
    assert tr.runtime.epoch == epoch
    tr._pump()
    assert tr.policy_pipeline.get(latest[1]) is not None
    tr.reset_history()  # An explicit reset still discards all sensor history.
    assert tr.latest is None and tr.next_reference is None
    assert not tr.runtime.history and tr.runtime.epoch == epoch + 1


def test_partial_history_still_waits_for_real_frames(live_transport):
    tr, clock, _ = live_transport
    prime(tr, clock, 3)
    assert tr.latest is None
    assert sum(tr.latest_status['history_mask']) == 3
    started = clock[0]
    tr.pad.buttons[tr.config.start_button] = True
    env = RealHILEnv(tr, tr.config, clock=lambda: clock[0] / 1e9)
    observation, _ = env.reset()
    assert 700_000_000 <= clock[0] - started < 800_000_000
    assert observation['history_mask'].all()


def test_old_full_history_cannot_start_without_fresh_sensors(live_transport):
    tr, clock, streaming = live_transport
    prime(tr, clock, 10)
    assert tr.latest is not None
    streaming[0] = False
    clock[0] += 300_000_000
    tr.pad.buttons[tr.config.start_button] = True
    env = RealHILEnv(tr, tr.config, clock=lambda: clock[0] / 1e9)
    with pytest.raises(InteractionUnavailable, match='no fresh full history'):
        env.reset()
    assert tr.latest is None and env.phase == 'idle'


def test_observation_driven_pump_uses_latest_without_full_history_or_freshness_wait(live_transport):
    tr, clock, streaming = live_transport
    tr.observation_driven = tr.runtime.latest_mode = True
    recorded = []
    tr.observation_hook = lambda stamp, latest, status: recorded.append((stamp, latest, status))
    prime(tr, clock, 1)
    assert tr.latest is not None and tr.latest[0]['history_mask'].sum() == 1
    streaming[0] = False
    prime(tr, clock, 12)
    assert tr.latest is not None and tr.latest[0]['history_mask'].all()
    assert len(recorded) == 13
    assert 'eef:old_receive' in tr.latest_status['timing_warnings']
    # RB release cannot issue another policy command from a snapshot used by human control.
    tr.pad.buttons[311] = True
    tr._pump()
    tr.pad.buttons[311] = False
    stamp = tr.latest[1]
    tr._pump()
    assert tr.policy_pipeline.get(stamp) is None
    prime(tr, clock, 1)
    assert tr.policy_pipeline.get(tr.latest[1]) is not None


def test_after_inference_keeps_inflight_candidates_across_rb_edges_but_not_stop(live_transport):
    tr, clock, _ = live_transport
    tr.observation_driven = tr.runtime.latest_mode = True
    tr.arbitration_mode = 'after-inference'
    prime(tr, clock, 1)
    stamp = tr.latest[1]
    assert tr.policy_pipeline.get(stamp) is not None
    tr.pad.buttons[311] = True
    tr._pump()
    assert tr.policy_pipeline.get(stamp) is not None
    prime(tr, clock, 1)
    stamp = tr.latest[1]
    assert tr.policy_pipeline.get(stamp) is not None  # Still infer while RB remains held.
    tr.pad.buttons[311] = False
    tr._pump()
    assert tr.policy_pipeline.get(stamp) is not None
    tr.pad.buttons[tr.config.stop_button] = True
    tr._pump()
    assert tr.policy_pipeline.get(stamp) is None
