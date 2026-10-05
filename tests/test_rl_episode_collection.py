"""Lifecycle checks without ROS or physical robot output."""
from types import SimpleNamespace
import json

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport, EpisodeTimeout, EpisodeSuccess
from omi_hil_rl.hil.collect_episodes import collect
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


class Human(FakeTransport):
    def interact(self, *args):
        result = super().interact(*args)
        result.source = 'human'
        result.audit = {'command_id': 'test-id'}
        return result


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
