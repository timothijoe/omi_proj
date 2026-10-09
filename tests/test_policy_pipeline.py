import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.policy_pipeline import LatestPolicy
from omi_hil_rl.hil.ros_transport import RosTransport


def wait_result(worker, stamp):
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        result = worker.get(stamp)
        if result is not None:
            return result
        time.sleep(.001)
    pytest.fail('worker timeout')


def test_latest_input_replaces_pending_and_owns_snapshot():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def infer(obs):
        calls.append(float(obs['x'][0]))
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
        return np.full(6, obs['x'][0], np.float32)
    worker = LatestPolicy(infer)
    try:
        worker.offer({'x': np.array([.1])}, 1)
        assert entered.wait(3)
        worker.offer({'x': np.array([.2])}, 2)
        obs = {'x': np.array([.3])}
        worker.offer(obs, 3)
        obs['x'][:] = .9
        release.set()
        result, elapsed = wait_result(worker, 3)
        assert np.allclose(result, .3)
        assert calls == [.1, .3]
        assert worker.get(2) is None
        assert elapsed >= 0
    finally:
        release.set()
        worker.close()
    assert not worker.thread.is_alive()


@pytest.mark.parametrize('consume_results', [False, True])
def test_rb_or_reset_invalidates_inflight_result(consume_results):
    entered, release = threading.Event(), threading.Event()
    def infer(obs):
        entered.set()
        assert release.wait(3)
        return np.zeros(6)
    worker = LatestPolicy(infer, consume_results=consume_results)
    try:
        worker.offer({'x': np.zeros(1)}, 1)
        assert entered.wait(3)
        worker.invalidate()
        release.set()
        worker.offer({'x': np.zeros(1)}, 2)
        wait_result(worker, 2)
        assert worker.get(1) is None
    finally:
        release.set()
        worker.close()


def test_nonfinite_worker_result_surfaces():
    worker = LatestPolicy(lambda obs: np.full(6, np.nan))
    try:
        worker.offer({'x': np.zeros(1)}, 1)
        with pytest.raises(RuntimeError, match='invalid normalized'):
            wait_result(worker, 1)
    finally:
        worker.close()


def test_old_receipt_observation_waits_for_fresh_precomputed_window():
    transport = RosTransport.__new__(RosTransport)
    now = [189_000_000]
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=now[0])))
    transport.pad = SimpleNamespace(buttons={311: False})
    worker = transport.policy_pipeline = LatestPolicy(lambda obs: np.zeros(6))
    try:
        obs = {'x': np.zeros(1)}
        transport.latest = obs, 100_000_000
        worker.offer(*transport.latest)
        wait_result(worker, 100_000_000)
        assert not transport._handoff_ready()  # prior 89ms receipt drift
        transport.latest = obs, 200_000_000
        now[0] = 211_000_000
        assert not transport._handoff_ready()
        worker.offer(*transport.latest)
        wait_result(worker, 200_000_000)
        assert transport._handoff_ready()
        worker.invalidate()
        transport.pad.buttons[311] = True
        assert transport._handoff_ready()  # RB does not wait for neural inference
        now[0] = 300_000_000
        assert not transport._handoff_ready()
    finally:
        worker.close()


def test_receipt_delay_pipeline_keeps_exact_transition_pairs():
    from omi_hil_rl.hil.config import HILConfig
    from omi_hil_rl.hil.environment import FakeTransport, RealHILEnv
    config = HILConfig(review='auto')
    transport = RosTransport.__new__(RosTransport)
    clock = [1_000_000_000]
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=clock[0])))
    transport.config = config
    transport.publisher = None
    transport.topic = '/test/policy'
    transport.pad = SimpleNamespace(buttons={311: False})
    transport.connected = True
    transport.events, transport.event_times, transport.receipts = set(), {}, {}
    transport.latest = None
    transport.human_only = False
    transport.stop = lambda: None
    worker = transport.policy_pipeline = LatestPolicy(lambda obs: np.full(6, .1))
    template = FakeTransport(config)._observation()
    sent = []
    def pump():
        clock[0] += 5_000_000
        reference = clock[0]//100_000_000*100_000_000
        if transport.latest is None or transport.latest[1] != reference:
            transport.latest = {k: v.copy() for k, v in template.items()}, reference
            transport.latest_eef_time = reference
            worker.offer(*transport.latest)
        for receipt in transport.receipts.values():
            receipt['finished'] = clock[0] >= receipt['finish_at']
        time.sleep(.0002)
    transport._pump = pump
    def publish(action, command_id):
        wire = action.tolist()
        sent.append((clock[0], transport.command_anchor_ns))
        transport.receipts[command_id] = dict(accepted=True, finished=False,
            delta_frame='base', arm='A', wire_action=wire, status='test_finished',
            finish_at=clock[0]+125_000_000)
        return wire
    transport._publish = publish
    env = RealHILEnv(transport, config)
    env.phase, env.episode = 'active', 'test-pipeline'
    env.started = time.monotonic()
    env.deadline = env.started+10
    try:
        env.previous, env.previous_stamp = transport.observe(env.deadline)
        for _ in range(20):
            old_obs, old_stamp = env.previous, env.previous_stamp
            candidate = worker.get(old_stamp)
            assert candidate is not None
            nxt, _, terminal, truncated, info = env.step(candidate[0])
            assert not terminal and not truncated
            assert info['observation_time_ns'] == old_stamp
            assert info['next_observation_time_ns'] == env.previous_stamp
            assert env.previous is nxt
            assert old_obs is not nxt
            assert np.allclose(info['executed_action'], .1)
        assert len(sent) == 20
        assert all(0 <= now-anchor < 100_000_000 for now, anchor in sent)
        assert max(now-anchor for now, anchor in sent) < 60_000_000
    finally:
        worker.close()


def test_release_edge_never_executes_pre_takeover_candidate():
    from omi_hil_rl.hil.config import HILConfig
    transport = RosTransport.__new__(RosTransport)
    clock = [10_000_000]
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=clock[0])))
    transport.config = HILConfig()
    transport.pad = SimpleNamespace(buttons={311: False})
    transport.policy_pipeline = SimpleNamespace(get=lambda stamp: None)
    transport._pipeline_released = True
    transport.connected = True
    transport.events, transport.event_times, transport.receipts = set(), {}, {}
    transport.human_only = False
    transport.topic = '/test/policy'
    transport.latest = ({'test': np.zeros(1)}, 100_000_000)
    transport.latest_eef_time = 100_000_000
    transport._handoff_ready = lambda: True
    sent = []
    def pump():
        if sent:
            clock[0] = 110_000_000
    transport._pump = pump
    def publish(action, command_id):
        sent.append(action.copy())
        transport.receipts[command_id] = dict(accepted=True, finished=True,
            delta_frame='base', arm='A', wire_action=action.tolist(), status='test')
        return action.tolist()
    transport._publish = publish
    result = transport.interact(np.ones(6), 0, time.monotonic()+2)
    assert result.source == 'human'
    assert np.array_equal(sent[0], np.zeros(6))
    assert np.array_equal(result.action_m_rad, np.zeros(6))
