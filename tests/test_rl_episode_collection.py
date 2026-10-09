"""Lifecycle checks without ROS or physical robot output."""
from types import SimpleNamespace
import json

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport, EpisodeTimeout, EpisodeSuccess, ButtonEvents, InteractionUnavailable
from omi_hil_rl.hil.collect_episodes import collect, collect_periodic
from omi_hil_rl.hil.exchange import read_episode
from omi_hil_rl.hil.ros_transport import RosTransport


def test_requested_episode_keys_are_distinct():
    from omi_hil_rl.hil.environment import ButtonEvents
    config = HILConfig()
    assert (config.start_button, config.success_button, config.stop_button) == (315, 308, 307)
    buttons = ButtonEvents(config)
    for code, event in [(315, 'start'), (308, 'success'), (307, 'manual_stop'),
                        (304, 'keep'), (305, 'discard')]:
        buttons.poll(True, {})
        assert buttons.poll(True, {code: True}) == {event}
        assert buttons.poll(True, {code: True}) == set()


def test_start_pressed_during_save_starts_next_episode_after_save(monkeypatch):
    import omi_hil_rl.hil.ros_transport as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    transport = RosTransport.__new__(RosTransport)
    transport.config = HILConfig()
    transport.home = None
    transport.connected = True
    transport.events = set()
    transport.event_times = {}
    transport.queue_start_during_save = True
    transport.pad = SimpleNamespace(buttons={})
    transport.publisher = None
    transport.allow_manual_reset = False
    transport.stop = lambda: None

    def pump():
        now[0] += .1
        if now[0] == 100.1:
            transport.events.add('start')
            transport.event_times['start'] = now[0]

    transport._pump = pump
    transport.idle_tick()
    assert transport.events == {'start'}
    now[0] = 105.
    started = transport.wait_start()
    assert started == 105.
    assert not transport.queue_start_during_save


class Human(FakeTransport):
    def interact(self, *args):
        result = super().interact(*args)
        result.source = 'human'
        result.audit = {'command_id': 'test-id'}
        return result


def test_human_periodic_session_is_separate_from_receipt_mode(tmp_path, monkeypatch):
    import omi_hil_rl.hil.periodic_control as periodic
    calls = []
    monkeypatch.setattr(periodic, 'run_periodic',
                        lambda actor, episodes, training: calls.append(
                            (actor.transport.collect_human, episodes, training, actor.version)))
    config = HILConfig(transport='ros', wrist_camera='required')
    transport = SimpleNamespace(receiver_info={'manual_topic': '/omi/controller_test/decision'})
    run = tmp_path / 'run'
    collect_periodic(run, config, transport, episodes=2)
    assert calls == [(True, 2, True, 0)]
    session = json.loads((run / 'session.json').read_text())
    assert session['mode'] == 'human_rl_periodic_v1'
    assert session['control_mode'] == 'observation_driven_10hz'
    assert session['timing_policy'] == 'diagnostic_only_v1'
    collect_periodic(run, config, transport, episodes=1, resume=True)
    assert calls[-1] == (True, 1, True, 0)


def test_repeated_success_autosave_without_learner(tmp_path):
    config = HILConfig(review='auto')
    transport = Human(config, success_step=2)
    results = collect(tmp_path / 'run', config, transport, episodes=2)
    assert len(results) == 2 and all(r['keep'] and r['episode_success'] for r in results)
    assert transport.allow_manual_reset and transport.collect_human
    for result in results:
        records = list(read_episode(tmp_path / 'run/episodes' / result['episode'], result))
        assert len(records) == 2 and records[-1]['reward'] == 1
        assert records[-1]['command_audit']['command_id'] == 'test-id'


@pytest.mark.parametrize('outcome', [EpisodeTimeout, EpisodeSuccess])
def test_between_commands_outcome_does_not_add_action(tmp_path, outcome):
    config = HILConfig(review='auto')
    class Transport(Human):
        def interact(self, *args):
            if self.steps == 1:
                raise outcome('between_commands')
            return super().interact(*args)
    result, = collect(tmp_path / 'run', config, Transport(config, success_step=99), episodes=1)
    assert result['keep'] and result['count'] == 1
    records = list(read_episode(tmp_path / 'run/episodes' / result['episode'], result))
    assert records[0]['terminated'] == (outcome is EpisodeSuccess)
    assert records[0]['truncated'] == (outcome is EpisodeTimeout)


def test_interrupt_preserves_prefix_but_never_ready(tmp_path):
    config = HILConfig(review='auto')
    class Transport(Human):
        def interact(self, *args):
            if self.steps:
                raise KeyboardInterrupt
            return super().interact(*args)
    with pytest.raises(KeyboardInterrupt):
        collect(tmp_path / 'run', config, Transport(config, success_step=99))
    summary = json.loads((tmp_path / 'run/summary.json').read_text())
    assert summary['closed'] and not summary['episodes'][0]['keep']
    assert not list((tmp_path / 'run').glob('episodes/*/ready.json'))
    assert len(list((tmp_path / 'run').glob('episodes/*/*.npz'))) == 1


def test_resume_retains_completed_episodes_and_quarantines_orphans(tmp_path):
    from omi_hil_rl.hil.exchange import atomic_json
    from dataclasses import replace
    config = HILConfig(review='auto')
    run = tmp_path / 'run'
    first = collect(run, config, Human(config, success_step=1), episodes=1)
    original = (run/'episodes'/first[0]['episode']/'000000.npz').read_bytes()
    orphan = run/'episodes'/'orphan'
    orphan.mkdir()
    atomic_json(orphan/'staging.json', dict(episode='orphan', contract=config.replay_contract()))
    results = collect(run, config, Human(config, success_step=1), episodes=1, resume=True)
    assert len(results) == 3
    assert sum(r['keep'] for r in results) == 2
    assert (orphan/'discarded.json').exists() and not (orphan/'ready.json').exists()
    assert (run/'episodes'/first[0]['episode']/'000000.npz').read_bytes() == original
    with pytest.raises(ValueError, match='mismatch'):
        collect(run, replace(config, episode_seconds=30), Human(config), resume=True)
    with pytest.raises(FileExistsError):
        collect(run, config, Human(config))


def test_success_before_send_stops_without_extra_motion():
    transport = RosTransport.__new__(RosTransport)
    transport._pump = lambda: None
    transport.connected = True
    transport.events = {'success'}
    transport.event_times = {'success': 1.}
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=0)))
    stops = []
    transport.stop = lambda: stops.append(True)
    transport._publish = lambda *a: pytest.fail('motion after success')
    with pytest.raises(EpisodeSuccess):
        transport.interact(np.zeros(6), 0, 10.)
    assert stops == [True]


def test_pairing_timeout_records_missing_receipt_after_stop(tmp_path):
    import time
    transport = RosTransport.__new__(RosTransport)
    transport._pump = lambda: None
    transport.connected = True
    transport.events = set()
    transport.event_times = {}
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=10_000_000)))
    transport.pad = SimpleNamespace(buttons={}, axes={})
    transport.config = HILConfig()
    transport.collect_human = True
    transport.human_only = False
    transport.receipts = {}
    transport.latest = None
    transport.runtime = SimpleNamespace(counts={}, rejected={})
    transport.pairing_report_path = tmp_path / 'pairing.json'
    transport._publish = lambda *args, **kwargs: [0.0] * 6
    stopped = []
    transport.stop = lambda: stopped.append(True)
    with pytest.raises(InteractionUnavailable, match='missing command receipt or causal next observation'):
        transport.interact(np.zeros(6, np.float32), 0, time.monotonic() + 1)
    report = json.loads(transport.pairing_report_path.read_text())
    assert stopped and report['reason'] == 'no_command_receipt'
    assert report['command_id'].startswith('hil:')


def test_reset_requires_rb_release_then_repress():
    from omi_hil_rl.real.gamepad_control import BTN_TR, Mapping
    transport = RosTransport.__new__(RosTransport)
    transport.allow_manual_reset = True
    transport.reset_requires_release = True
    transport.publisher = object()
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={BTN_TR: True}, axes={})
    transport.mapping = Mapping()
    transport.config = HILConfig()
    sent = []
    transport._publish = lambda *a: sent.append(a)
    transport.stop = lambda: None
    transport._manual_reset_tick()
    assert not sent
    transport.pad.buttons[BTN_TR] = False
    transport._manual_reset_tick()
    assert not sent and not transport.reset_requires_release
    transport.pad.buttons[BTN_TR] = True
    transport._manual_reset_tick()
    assert len(sent) == 1 and len(sent[0]) == 1  # no command ID, not a sample


def test_back_home_takes_priority_over_rb_between_episodes():
    from omi_hil_rl.real.gamepad_control import BTN_TR, Mapping
    transport = RosTransport.__new__(RosTransport)
    transport.allow_manual_reset = True
    transport.publisher = object()
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={BTN_TR: True, 314: True}, axes={})
    transport.mapping = Mapping()
    transport.config = HILConfig()
    transport.home = SimpleNamespace(button_code=314, status='returning', future=None, plan=object(),
                                     tick=lambda *_: ('human_home', np.array([.001, 0, 0, 0, 0, 0]), [1., 0, 0, 0, 0, 0]))
    transport.home_active = False
    transport.home_status = ''
    transport.reset_held = True
    sent, stopped = [], []
    transport._publish = lambda action, **kwargs: sent.append((action.copy(), kwargs))
    transport.stop = lambda: stopped.append(True)
    assert transport._manual_reset_tick()
    assert len(sent) == 1 and sent[0][1] == dict(convention='sdk-base-aligned', source='human_home')
    assert sent[0][0][0] == pytest.approx(.001)
    assert transport.reset_requires_release and not transport.reset_held
    assert not stopped
    transport.home.plan = None
    transport.home.tick = lambda *_: None
    transport.pad.buttons[314] = False
    assert transport._manual_reset_tick()
    assert stopped == [True]
    assert len(sent) == 1


def test_back_held_during_episode_requires_release_after_episode():
    transport = RosTransport.__new__(RosTransport)
    transport.allow_manual_reset = True
    transport.publisher = object()
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={314: True}, axes={})
    transport.config = HILConfig()
    transport.home = SimpleNamespace(button_code=314, previous_x=False, status='', future=None, plan=None)
    calls = []
    transport.home.tick = lambda *_: calls.append(True)
    transport.home_active = False
    transport.home_status = ''
    transport.home_requires_release = True
    transport.reset_requires_release = True
    transport.stop = lambda: None
    transport._publish = lambda *_: pytest.fail('held Back must not start home')
    assert transport._manual_reset_tick()
    assert not calls and transport.home.previous_x
    transport.pad.buttons[314] = False
    assert transport._manual_reset_tick()
    assert not calls and not transport.home_requires_release
    assert not transport._manual_reset_tick()
    assert calls


def test_collector_back_short_tap_reaches_home_service():
    from concurrent.futures import Future
    from omi_hil_rl.real.gamepad_control import Mapping
    from omi_hil_rl.real.gamepad_home import GamepadHome
    requests = []
    home = GamepadHome(clock=lambda: 0., button_code=314, require_rb=False)
    home.client = SimpleNamespace(service_is_ready=lambda: True,
        call_async=lambda _: requests.append(Future()) or requests[-1])
    home.request_type = lambda: None
    transport = RosTransport.__new__(RosTransport)
    transport.allow_manual_reset = True
    transport.publisher = object()
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={}, axes={}, button_events=())
    transport.mapping = Mapping()
    transport.config = HILConfig()
    transport.home = home
    transport.home_active = False
    transport.home_requires_release = True
    transport.home_status = ''
    transport.reset_requires_release = True
    transport.reset_held = False
    transport.stop = lambda: None
    transport._publish = lambda *_: pytest.fail('no motion before home response')
    transport._manual_reset_tick()  # release after startup
    transport.pad.button_events = ((314, True, False), (314, False, False))
    assert transport._manual_reset_tick()
    assert len(requests) == 1 and home.status == '正在读取当前关节并计算返回位姿'


def test_back_home_wire_is_base_aligned_and_not_a_training_command(monkeypatch):
    import sys
    class Message:
        def __init__(self, data=None):
            self.data = data
            self.layout = SimpleNamespace(dim=[])
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', SimpleNamespace(
        Float64MultiArray=Message, MultiArrayDimension=Message))
    transport = RosTransport.__new__(RosTransport)
    transport.topic = '/omi/action/manual_decision'
    transport.convention = 'sdk-x-forward-z-left'
    transport.config = HILConfig(transport='ros')
    transport.last_owner = None
    transport.node = SimpleNamespace(count_publishers=lambda topic: 1 if topic == transport.topic else 0,
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=123)))
    sent = []
    transport.publisher = SimpleNamespace(publish=sent.append)
    transport.trace_publisher = None
    wire = transport._publish(np.array([0., .001, 0., 0., 0., 0.]),
                              convention='sdk-base-aligned', source='human_home')
    assert wire == pytest.approx([0., 1., 0., 0., 0., 0.])
    assert sent[0].data == wire and sent[0].layout.dim == []
    trace = transport.last_command_trace
    assert trace['action_source'] == 'human_home'
    assert trace['output_convention'] == 'sdk-base-aligned'
    assert trace['command_id'] is None and trace['label_candidate'] is False
    assert trace['normalized_action'] is None


def test_collector_polls_ab_gripper_without_episode_events():
    from omi_hil_rl.real.gamepad_gripper import GripperButtons
    states = iter([
        ({}, ()),
        ({}, ((304, True, False), (304, False, False))),
        ({}, ()),
        ({}, ((305, True, False), (305, False, False))),
    ])
    class Pad:
        button_events = ()
        axes = {}
        buttons = {}
        def poll(self):
            self.buttons, self.button_events = next(states)
            return True
    selected = []
    selector = GripperButtons()
    transport = RosTransport.__new__(RosTransport)
    transport.rclpy = SimpleNamespace(ok=lambda: True, spin_once=lambda *_, **__: None)
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=1)))
    transport.pad = Pad()
    transport.gripper = SimpleNamespace(tick=lambda connected, buttons, transitions:
        selected.append(selector.select(connected, buttons, transitions)))
    transport.config = HILConfig(review='auto')
    transport.buttons = ButtonEvents(transport.config)
    transport.events = set()
    transport.event_times = {}
    transport.next_reference = None
    transport.latest = None
    transport.runtime = SimpleNamespace(window=lambda _: (None, None))
    for _ in range(4):
        transport._pump()
    assert selected == [None, 'close', None, 'open']
    assert transport.events == set()


def test_transport_close_releases_gripper_even_if_ros_cleanup_fails():
    transport = RosTransport.__new__(RosTransport)
    closed = []
    transport.pad = SimpleNamespace(close=lambda: closed.append('pad'))
    transport.node = SimpleNamespace(destroy_node=lambda: (_ for _ in ()).throw(RuntimeError('ROS cleanup')))
    transport.gripper = SimpleNamespace(close=lambda: closed.append('gripper'))
    with pytest.raises(RuntimeError, match='ROS cleanup'):
        transport.close()
    assert closed == ['pad', 'gripper']


def test_review_required_before_ready_and_next_episode(tmp_path):
    config = HILConfig(review='manual')
    reviews = []
    class Transport(Human):
        def wait_review(self):
            assert len(list((tmp_path/'run').glob('episodes/*/ready.json'))) == 0
            reviews.append(True)
            return False
    results = collect(tmp_path/'run', config, Transport(config, success_step=1), episodes=2)
    assert len(reviews) == 2 and all(not r['keep'] for r in results)


def test_auto_keep_never_waits_for_review_and_requires_rb_release(tmp_path):
    config = HILConfig(review='auto')
    class Transport(Human):
        def wait_review(self):
            pytest.fail('automatic collection must not request approval')
    transport = Transport(config, success_step=1)
    result, = collect(tmp_path/'auto', config, transport, episodes=1)
    assert result['keep'] and transport.reset_requires_release
