import json
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.periodic_control import PeriodicClock, choose_action, pair_status, run_periodic
from omi_hil_rl.hil.config import HILConfig


def test_clock_skips_missed_ticks_without_catchup_burst():
    clock = PeriodicClock(0)
    assert clock.due(0)['skipped_ticks'] == 0
    assert clock.due(.05) is None
    assert clock.due(.35)['skipped_ticks'] == 2
    assert clock.due(.35) is None
    assert clock.due(.41) is not None


def test_manual_priority_and_no_stale_or_repeated_policy():
    config = HILConfig()
    tr = SimpleNamespace(connected=True, pad=SimpleNamespace(buttons={}, axes={}), config=config,
        latest=({}, 1_000_000_000),
        mapping=SimpleNamespace(action=lambda axes: np.ones(6)*.0001),
        node=SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=1_050_000_000))),
        policy_pipeline=SimpleNamespace(get=lambda stamp: (np.ones(6)*.2, 5.)))
    a, _, gate, _, used = choose_action(tr, None, True)
    assert gate == 'policy' and np.any(a)
    assert not np.any(choose_action(tr, used, True)[0])
    tr.latest = ({}, 900_000_000)
    assert not np.any(choose_action(tr, None, True)[0])
    tr.latest = None
    tr.pad.buttons[311] = True
    assert choose_action(tr, None, True)[1:3] == ('human', 'human')
    assert np.any(choose_action(tr, None, True)[0])
    assert not np.any(choose_action(tr, None, False)[0])


def test_human_periodic_collects_zero_and_rb_actions_as_human():
    tr = SimpleNamespace(connected=True, collect_human=True,
        pad=SimpleNamespace(buttons={}, axes={}), latest=({}, 100),
        mapping=SimpleNamespace(action=lambda axes: np.ones(6, np.float32)),
        node=SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=101))))
    action, source, gate, _, _ = choose_action(tr, None, False)
    assert source == 'human' and gate == 'receiver_handshake' and not np.any(action)
    action, source, gate, _, _ = choose_action(tr, None, True)
    assert source == 'human' and gate == 'human' and not np.any(action)
    tr.pad.buttons[311] = True
    action, source, gate, _, _ = choose_action(tr, None, True)
    assert source == 'human' and gate == 'human' and np.all(action == 1)


def test_replacement_is_not_fabricated_as_completed_training_action():
    tick = dict(command_id='c', observation_present=True, observation_reference_ns=1,
                command_send_ns=2, wire_action=[0.]*6)
    nxt = dict(observation_present=True, observation_reference_ns=3)
    assert pair_status(tick, nxt, []) == 'missing_receipt'
    receipt = dict(command_id='c', accepted=False, finished=True, wire_action=[0.]*6,
                   arm='A', delta_frame='base', control_mode='velocity_hold', status='queue_replaced')
    assert pair_status(tick, nxt, [receipt]) == 'partial_or_replaced_command'
    receipt.update(accepted=True, status='velocity_window_sent')
    assert pair_status(tick, nxt, [receipt]) == 'matched_not_execution_confirmed'


def test_nominal_boundary_replacement_is_accepted_command_not_early_failure():
    tick = dict(command_id='c', observation_present=True,
                observation_reference_ns=0, command_send_ns=1_000_000,
                wire_action=[0.1] * 6)
    following = dict(observation_present=True, observation_reference_ns=100_000_000,
                     command_send_ns=101_000_000)
    initial = dict(command_id='c', accepted=True, finished=False,
                   status='queue_accepted', wire_action=[0.1] * 6,
                   arm='A', delta_frame='base', control_mode='velocity_hold')
    replacement = dict(initial, accepted=False, finished=True,
                       status='queue_replaced', timestamp_ns=101_100_000)
    assert pair_status(tick, following, [initial, replacement]) == 'matched_not_execution_confirmed'
    replacement['timestamp_ns'] = 50_000_000
    assert pair_status(tick, following, [initial, replacement]) == 'partial_or_replaced_command'


@pytest.mark.parametrize('interrupt', [False, True])
def test_delayed_receipts_do_not_block_periodic_sends(tmp_path, monkeypatch, interrupt):
    import omi_hil_rl.hil.periodic_control as module
    now = [100.]
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    config = HILConfig(episode_seconds=1.2)
    sent, pending, states, monitor_events = [], [], [], []
    interrupted = [False]
    class Transport:
        def __init__(self):
            self.config = config
            self.connected = True
            self.pad = SimpleNamespace(buttons={}, axes={})
            self.events, self.event_times = set(), {}
            self.consumed = None
            self.policy_pipeline = SimpleNamespace(take=self.take)
            self.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(now[0]*1e9))))
            self.latest = None
        def wait_start(self): return now[0]
        def start_episode(self): pass
        def stop(self): pass
        def idle_tick(self): pass
        def take(self):
            if self.latest[1] == self.consumed:
                return None
            self.consumed = self.latest[1]
            return (*self.latest, np.ones(6)*.1, 5.)
        def _pump(self):
            now[0] += .01
            if interrupt and not interrupted[0] and len(sent) >= 6:
                interrupted[0] = True
                raise KeyboardInterrupt
            stamp = int(now[0]*10)*100_000_000
            if self.latest is None or self.latest[1] != stamp:
                self.latest = ({'test': np.zeros(1)}, stamp)
                self.observation_hook(stamp, self.latest, {})
            for deadline, receipt in list(pending):
                if now[0] >= deadline:
                    pending.remove((deadline, receipt))
                    hook = getattr(self, 'receipt_hook', None)
                    if hook: hook(receipt)
        def _publish(self, action, command_id):
            sent.append((now[0], action.copy()))
            self.last_command_trace = {}
            receipt = dict(command_id=command_id, accepted=True, finished=False,
                status='queue_accepted', control_mode='velocity_hold', arm='A', delta_frame='base',
                nominal_duration_s=.1, action_source=self.last_owner, wire_action=action.tolist())
            pending.append((now[0]+.01, receipt))
            pending.append((now[0]+.45, dict(receipt, finished=True, status='velocity_window_sent')))
            return action.tolist()
    tr = Transport()
    actor = SimpleNamespace(transport=tr, config=config, run=tmp_path, version=295,
                            load=lambda: None, close_pipeline=lambda: None,
                            state=lambda phase, **details: states.append(phase),
                            periodic_monitor_start=lambda episode, started:
                                monitor_events.append(('start', episode, started)),
                            periodic_monitor_end=lambda episode:
                                monitor_events.append(('end', episode)))
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            run_periodic(actor, 1)
    else:
        run_periodic(actor, 1)
    assert len(sent) >= (6 if interrupt else 11)
    assert max(np.diff([t for t, _ in sent])) < .12
    assert not np.any(sent[0][1])  # zero handshake before trust
    assert any(np.any(a) for t, a in sent if t < 100.45)  # no completion wait
    report = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert report['reason'] == ('interrupted' if interrupt else 'timeout')
    assert not report['training_ready']
    assert not list(tmp_path.rglob('ready.json'))
    assert 'EPISODE_RECORDED' in states
    assert monitor_events[0][0] == 'start' and monitor_events[0][2] == 100.
    assert monitor_events[-1] == ('end', monitor_events[0][1])


def test_human_periodic_exports_valid_accepted_command_segments(tmp_path, monkeypatch):
    import omi_hil_rl.hil.periodic_control as module
    from omi_hil_rl.training.transition_replay import _spaces
    now = [100.]
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    config = HILConfig(transport='ros', wrist_camera='required', episode_seconds=1.2)
    spaces, _ = _spaces(config.replay_contract())
    observation = {key: np.zeros(space.shape, space.dtype)
                   for key, space in spaces.spaces.items()}
    observation['history_mask'][:] = 1
    observation['camera_mask'][:] = 1
    pending = []

    class Transport:
        def __init__(self):
            self.connected = True
            self.collect_human = True
            self.pad = SimpleNamespace(buttons={}, axes={})
            self.events, self.event_times = set(), {}
            self.mapping = SimpleNamespace(action=lambda axes: np.zeros(6, np.float32))
            self.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
                now=lambda: SimpleNamespace(nanoseconds=int(now[0]*1e9))))
            self.latest = None
            self.latest_eef_time = 0

        def wait_start(self): return now[0]
        def start_episode(self): pass
        def stop(self): pass
        def idle_tick(self): pass

        def _pump(self):
            now[0] += .01
            stamp = int((int(now[0]*10)/10)*1e9)
            self.latest = (observation, stamp)
            self.latest_eef_time = int(now[0]*1e9)
            for deadline, receipt in list(pending):
                if now[0] >= deadline:
                    pending.remove((deadline, receipt))
                    if getattr(self, 'receipt_hook', None): self.receipt_hook(receipt)

        def _publish(self, action, command_id):
            self.last_command_trace = {}
            wire = [0.] * 6
            receipt = dict(command_id=command_id, accepted=True, finished=True,
                           status='velocity_zero_stopped', control_mode='velocity_hold',
                           arm='A', delta_frame='base', nominal_duration_s=.1,
                           action_source='human', wire_action=wire,
                           timestamp_ns=int((now[0]+.01)*1e9))
            pending.append((now[0]+.01, receipt))
            return wire

    transport = Transport()
    completed = []
    actor = SimpleNamespace(transport=transport, config=config, run=tmp_path, version=0,
                            load=lambda: None, close_pipeline=lambda: None,
                            state=lambda phase, **details: None,
                            finished=lambda result: completed.append(result))
    run_periodic(actor, 1, training=True)
    audit = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert audit['training_ready'] and audit['transitions'] > 0
    assert completed and completed[0]['keep']
    assert list(tmp_path.rglob('ready.json'))
    ticks = []
    for path in sorted(tmp_path.glob('periodic_episodes/*/[0-9]*.npz')):
        with np.load(path, allow_pickle=False) as data:
            ticks.append(json.loads(str(data['metadata'])))
    ages_ms = [(tick['command_send_ns'] - tick['observation_reference_ns']) / 1e6
               for tick in ticks if tick['observation_present']]
    assert ages_ms and all(0 <= age < 20 for age in ages_ms)
