import json
import threading
import time
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import import_ready, read_episode
from omi_hil_rl.hil.periodic_bc_label import validate_bc_label
from omi_hil_rl.hil.periodic_control import PeriodicAudit, observation_action, run_periodic
from omi_hil_rl.hil.policy_pipeline import LatestPolicy
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.stack_shadow import StackObservations
from omi_hil_rl.training.transition_replay import TransitionReplay


def wait_until(predicate):
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.001)
    pytest.fail('worker timeout')


def test_latest_samples_reuse_old_frames_and_take_arrivals_after_lattice_point():
    runtime = StackObservations(GridProfile('required').CONTRACT)
    runtime.latest_mode = True
    runtime.profile.decode = lambda key, msg: (msg.stamp, msg.value)
    for key in runtime.topics.values():
        if key in ('rgb', 'wrist_rgb'):
            value = np.full((3, 128, 128), 42, np.uint8)
        elif key == 'eef':
            value = np.array([.5, .1, .8, 0, 0, 0, 1], np.float32)
        else:
            value = np.zeros((1 if key.endswith('depth') else 2, 16, 24), np.float32)
        # Both a very old header and receipt just after the nominal observation tick.
        assert runtime.ingest(key, NS(stamp=1, value=value), 1_005_000_000)
    (first, mask), status = runtime.window(1_000_000_000)
    assert mask.tolist() == [False]*9+[True]
    assert status['source_receive_ns']['eef'] == 1_005_000_000
    assert 'eef:old_header' in status['timing_warnings']
    assert 'eef:received_after_reference' in status['timing_info']
    assert 'eef:received_after_reference' not in status['timing_warnings']
    (second, _), status = runtime.window(2_000_000_000)
    np.testing.assert_array_equal(first['state'][-1], second['state'][-1])
    assert 'eef:old_receive' in status['timing_warnings']
    # Missing/invalid numeric data is still distinguishable from an old real frame.
    assert not runtime.ingest('eef', NS(stamp=1, value=np.full(7, np.nan)), 2_001_000_000)
    assert runtime.window(2_100_000_000)[0] is None


def test_completed_slow_result_is_delivered_before_latest_pending_input():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def infer(obs):
        calls.append(float(obs['x'][0]))
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
        return np.full(6, obs['x'][0], np.float32)
    worker = LatestPolicy(infer, consume_results=True)
    try:
        worker.offer({'x': np.array([.1])}, 1)
        assert entered.wait(3)
        worker.offer({'x': np.array([.2])}, 2)
        worker.offer({'x': np.array([.3])}, 3)
        release.set()
        wait_until(lambda: worker.get(1) is not None)
        assert calls == [.1]  # Completion is not overwritten before the sender consumes it.
        obs, stamp, action, elapsed = worker.take()
        assert stamp == 1 and obs['x'][0] == .1 and np.allclose(action, .1)
        wait_until(lambda: worker.get(3) is not None)
        assert worker.take()[1] == 3 and calls == [.1, .3]
        assert worker.take() is None
    finally:
        release.set()
        worker.close()


def test_slow_candidate_keeps_its_input_and_is_not_replaced_by_zero():
    config = HILConfig()
    old = {'x': np.array([1.])}
    results = [None, (old, 1_000_000_000, np.ones(6)*.2, 230.)]
    tr = NS(latest=({'x': np.array([2.])}, 1_200_000_000), config=config,
            pad=NS(buttons={}), policy_pipeline=NS(take=lambda: results.pop(0)))
    assert observation_action(tr, None, {'policy': True}) is None
    action, source, gate, snapshot, stamp, elapsed = observation_action(tr, None, {'policy': True})
    assert gate == source == 'policy' and np.any(action)
    assert snapshot[0] is old and stamp == 1_000_000_000 and elapsed == 230.


def test_timing_warnings_survive_export_bc_validation_and_actual_replay_import(tmp_path):
    config = HILConfig(wrist_camera='required')
    contract = config.replay_contract()
    obs = FakeTransport(config)._observation()
    # New collection starts without waiting for ten frames of history.
    obs['history_mask'][:] = 0
    obs['history_mask'][-1] = 1
    obs['camera_mask'][:] = 0
    obs['camera_mask'][-1] = 1
    action = np.full(6, .2, np.float32)
    physical = config.physical_action(action)
    wire = output_action(physical, config.sdk_convention)
    audit = PeriodicAudit(tmp_path, 'source', contract, 7, training=True, timing_policy='diagnostic_only_v1')
    for i in range(3):
        stamp = 1_000_000_000+i*100_000_000
        send = stamp+160_000_000  # Sending and acceptance after the next input snapshot.
        trace = dict(command_id=str(i), command_send_ns=send, observation_reference_ns=stamp,
                     action_source='human', label_candidate=True, execution_confirmed=False,
                     action_contract=contract['action_contract'], output_convention=config.sdk_convention,
                     normalized_action=action.tolist(), action_m_rad=physical.tolist(), wire_action=wire)
        audit.submit('tick', (dict(command_id=str(i), action_source='human', gate='human', command_trace=trace,
            arbitration_mode='after-inference',
            arbitration=dict(mode='after-inference', rb=True, policy_candidate_normalized=[-.5]*6),
            observation_present=True, observation_reference_ns=stamp, command_send_ns=send,
            eef_receive_ns=1, normalized_action=action.tolist(), wire_action=wire), obs))
        audit.submit('receipt', dict(command_id=str(i), accepted=True, finished=False, status='queue_accepted',
            timestamp_ns=send+80_000_000, wire_action=wire, arm='A', delta_frame='base',
            action_source='human', control_mode='velocity_hold', nominal_duration_s=.1))
    boundary = (dict(observation_present=True, observation_reference_ns=1_300_000_000,
                     eef_receive_ns=1, command_send_ns=1_400_000_000), obs)
    result = audit.finish(boundary, dict(episode='source', policy_version=7, success=True, reason='success'))
    assert result['transitions'] == 3 and result['excluded'] == {}
    assert len(result['segments']) == 1 and result['success_label_recorded']
    assert result['timing_diagnostics']['missing_causal_eef'] == 3
    assert result['timing_diagnostics']['acceptance_too_late'] == 3
    ready = next(tmp_path.glob('episodes/*/ready.json'))
    records = list(read_episode(ready.parent, json.loads(ready.read_text())))
    for record in records:
        validate_bc_label(contract, record['executed_action'], record)
        assert record['command_audit']['timing_policy'] == 'diagnostic_only_v1'
        assert record['command_audit']['arbitration_mode'] == 'after-inference'
        assert record['command_audit']['arbitration']['policy_candidate_normalized'] == [-.5]*6
        np.testing.assert_array_equal(record['executed_action'], action)
    replay = TransitionReplay(tmp_path/'replay', contract, 8, prefetch=False)
    try:
        assert import_ready(tmp_path, replay) == 3
        assert replay.buffer.size() == 3
    finally:
        replay.close()


def test_long_inference_does_not_stop_episode_or_drop_observation_ticks(tmp_path, monkeypatch, capsys):
    import omi_hil_rl.hil.periodic_control as module
    now = [100.]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: now[0]))
    config = HILConfig(episode_seconds=2.)
    sent = []
    class Transport:
        connected = True
        latest = None
        last_owner = None
        config = None
        pad = NS(buttons={}, axes={})
        events, event_times = set(), {}
        node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=round(now[0]*1e9))))
        def wait_start(self): return now[0]
        def start_episode(self): pass
        def stop(self): pass
        def idle_tick(self): pass
        def _pump(self):
            now[0] += .01
            stamp = int(round(now[0]*1e9))//100_000_000*100_000_000
            if self.latest is None or self.latest[1] != stamp:
                self.latest = ({'test': np.array([stamp])}, stamp)
                if getattr(self, 'observation_hook', None):
                    self.observation_hook(stamp, self.latest, {})
                if not hasattr(self, 'inference_input'):
                    self.inference_input = self.latest
            if getattr(self, 'pending', None):
                receipt, self.pending = self.pending, None
                if self.receipt_hook: self.receipt_hook(receipt)
        def take(self):
            if now[0] < 101.35 or getattr(self, 'taken', False): return None
            self.taken = True
            return (*self.inference_input, np.ones(6)*.2, 1300.)
        def _publish(self, action, command_id):
            sent.append((now[0], self.command_anchor_ns, action.copy()))
            self.last_command_trace = {'command_send_ns': round(now[0]*1e9)}
            self.pending = dict(command_id=command_id, accepted=True, finished=False, status='queue_accepted',
                timestamp_ns=round(now[0]*1e9), wire_action=action.tolist(), arm='A', delta_frame='base',
                action_source='policy', control_mode='velocity_hold', nominal_duration_s=.1)
            return action.tolist()
    tr = Transport()
    tr.config, tr.policy_pipeline = config, NS(take=tr.take)
    actor = NS(transport=tr, config=config, run=tmp_path, version=7, policy=True,
               load=lambda: None, close_pipeline=lambda: None, state=lambda *a, **kw: None)
    run_periodic(actor, 1)
    nonzero = [(t, stamp) for t, stamp, action in sent if np.any(action)]
    assert len(sent) == 2 and len(nonzero) == 1  # Handshake, then the late result; no timeout-zero commands.
    assert 101.35 <= nonzero[0][0] < 101.38 and nonzero[0][1] == 100_000_000_000
    report = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert report['reason'] == 'timeout' and report['observation_ticks'] >= 20
    assert len(list(tmp_path.glob('periodic_episodes/*/observations/*.npz'))) == report['observation_ticks']
    assert 'ACTION_TIMING:' in capsys.readouterr().out
