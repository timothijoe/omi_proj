import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.periodic_control import observation_action, run_periodic


@pytest.mark.parametrize('rb_at_completion', [False, True])
def test_deferred_choice_uses_rb_and_axes_at_completion_and_original_observation(rb_at_completion):
    config = HILConfig()
    old = {'test': np.array([1.])}
    results = [None, (old, 1_000_000_000, np.ones(6)*.2, 220.)]
    tr = NS(arbitration_mode='after-inference', config=config,
            latest=({'test': np.array([2.])}, 1_200_000_000),
            pad=NS(buttons={311: not rb_at_completion}, axes={'x': .0001}),
            mapping=NS(action=lambda axes: np.full(6, axes['x'], np.float32)),
            policy_pipeline=NS(take=lambda: results.pop(0)))
    verified = {'human': True, 'policy': True}
    assert observation_action(tr, None, verified) is None
    tr.pad.buttons[311] = rb_at_completion
    tr.pad.axes['x'] = .0002
    action, source, gate, snapshot, stamp, elapsed = observation_action(tr, None, verified)
    assert source == gate == ('human' if rb_at_completion else 'policy')
    assert snapshot[0] is old and stamp == 1_000_000_000 and elapsed == 220.
    np.testing.assert_allclose(action, .0002 if rb_at_completion else config.physical_action(np.ones(6)*.2))
    assert tr.last_arbitration['rb'] == rb_at_completion
    assert tr.last_arbitration['policy_candidate_normalized'] == [.2]*6


def test_immediate_and_human_only_do_not_wait_for_inference():
    def must_not_wait():
        pytest.fail('manual immediate path waited for policy')
    tr = NS(arbitration_mode='immediate', latest=({}, 100),
            pad=NS(buttons={311: True}, axes={}),
            mapping=NS(action=lambda axes: np.ones(6, np.float32)*.0001),
            policy_pipeline=NS(take=must_not_wait))
    assert observation_action(tr, None, {'human': True})[1:3] == ('human', 'human')
    tr.arbitration_mode, tr.collect_human = 'after-inference', True
    assert observation_action(tr, None, {'human': True})[1:3] == ('human', 'human')
    tr.collect_human = False
    assert observation_action(tr, None, {'human': True}, policy=False)[1:3] == ('human', 'human')


@pytest.mark.parametrize('mode', ['after-inference', 'immediate'])
@pytest.mark.parametrize('end', ['timeout', 'manual_stop', 'disconnect'])
def test_arbitration_loop_switches_at_completion_or_rb_edge(tmp_path, monkeypatch, mode, end):
    import omi_hil_rl.hil.periodic_control as module
    now = [100.]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: now[0]))
    config = HILConfig(episode_seconds=.7)
    sent, stops = [], []

    class Transport:
        connected = True
        latest = None
        events, event_times = set(), {}
        pad = NS(buttons={}, axes={})
        node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=round(now[0]*1e9))))
        mapping = NS(action=lambda axes: np.full(6, .0001, np.float32))
        results = [(100.03, 100_000_000_000), (100.13, 100_100_000_000),
                   (100.33, 100_200_000_000), (100.43, 100_400_000_000)]
        def wait_start(self): return now[0]
        def start_episode(self): pass
        def idle_tick(self): pass
        def stop(self): stops.append(now[0])
        def _pump(self):
            now[0] = round(now[0]+.01, 2)
            stamp = round(now[0]*1e9)//100_000_000*100_000_000
            self.latest = ({'test': np.array([stamp])}, stamp)
            self.pad.buttons[311] = now[0] >= 100.2
            if end == 'manual_stop' and now[0] >= 100.25:
                self.events.add('manual_stop')
            if end == 'disconnect' and now[0] >= 100.25:
                self.connected = False
            if getattr(self, 'pending', None):
                receipt, self.pending = self.pending, None
                if self.receipt_hook: self.receipt_hook(receipt)
        def take(self):
            if not self.results or now[0] < self.results[0][0]: return None
            due, stamp = self.results.pop(0)
            return {'test': np.array([stamp])}, stamp, np.ones(6)*.2, 130.
        def _publish(self, action, command_id):
            sent.append((now[0], self.last_owner, action.copy(), self.command_anchor_ns))
            self.last_command_trace = dict(command_send_ns=round(now[0]*1e9))
            wire = action.tolist()
            self.pending = dict(command_id=command_id, accepted=True, status='queue_accepted',
                finished=False, timestamp_ns=round(now[0]*1e9), wire_action=wire,
                control_mode='velocity_hold', arm='A', delta_frame='base', nominal_duration_s=.1,
                action_source=self.last_owner)
            return wire

    tr = Transport()
    tr.config, tr.arbitration_mode, tr.policy_pipeline = config, mode, NS(take=tr.take)
    actor = NS(transport=tr, config=config, run=tmp_path, version=1, policy=True,
               load=lambda: None, close_pipeline=lambda: None, state=lambda *args, **kw: None)
    run_periodic(actor, 1)
    report = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert report['arbitration_mode'] == mode
    if mode == 'after-inference':
        assert not any(100.2 <= t < 100.25 for t in stops)
        assert not any(100.2 <= t < 100.33 for t, *_ in sent)
    else:
        assert 100.2 in stops
        assert any(t == 100.2 and owner == 'human' for t, owner, *_ in sent)
    if end != 'timeout':
        assert any(abs(t-100.25) < .001 for t in stops)
        assert not any(t >= 100.25 for t, *_ in sent)
        assert report['reason'] == ('manual_stop' if end == 'manual_stop' else 'gamepad disconnected')
    elif mode == 'after-inference':
        assert any(t == 100.33 and owner == 'human' for t, owner, *_ in sent)
        tick = next(tmp_path.glob('periodic_episodes/*/000003.npz'))
        with np.load(tick, allow_pickle=False) as data:
            meta = json.loads(str(data['metadata']))
            assert meta['arbitration_mode'] == mode and meta['action_source'] == 'human'
            assert meta['arbitration']['rb'] and meta['arbitration']['policy_candidate_normalized'] == [.2]*6
            assert meta['observation_reference_ns'] == 100_400_000_000
