"""No ROS publishers: alternating orchestration and short button taps."""
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.alternating import Alternating, wait_worker
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport, ButtonEvents
from omi_hil_rl.hil.exchange import atomic_json


def test_short_press_release_survives_one_poll():
    events = ButtonEvents(HILConfig())
    events.poll(True, {})
    assert events.poll(True, {308: False}, [(308, True, False), (308, False, False)]) == {'success'}
    assert not events.poll(True, {})
    assert not events.poll(True, {308: True}, [(308, True, True)])
    assert not events.poll(True, {308: True})


def test_linux_reader_retains_short_tap(monkeypatch):
    import struct
    from omi_hil_rl.real.linux_gamepad import LinuxGamepad
    pad = LinuxGamepad()
    pad.fd, pad.button_map = 123, [308]
    queue = iter([struct.pack('IhBB', 0, 1, 1, 0), struct.pack('IhBB', 1, 0, 1, 0)])
    def read(fd, size):
        try:
            return next(queue)
        except StopIteration:
            raise BlockingIOError
    monkeypatch.setattr('os.read', read)
    assert pad.poll()
    assert pad.buttons[308] is False
    assert pad.button_events == [(308, True, False), (308, False, False)]


def test_uncoordinated_learner_is_rejected(tmp_path):
    from omi_hil_rl.hil.learner import run_learner
    atomic_json(tmp_path/'alternating_state.json', dict(phase='ACTIVE', task=None))
    with pytest.raises(ValueError, match='current scheduler task'):
        run_learner(tmp_path, HILConfig())


def test_worker_keeps_parent_responsive_and_checks_failure(tmp_path):
    ticks = []
    wait_worker([sys.executable, '-c', 'import time; time.sleep(.1)'],
                tmp_path/'worker.log', lambda: ticks.append(1))
    assert len(ticks) > 1
    with pytest.raises(RuntimeError, match='exited 3'):
        wait_worker([sys.executable, '-c', 'raise SystemExit(3)'], tmp_path/'worker.log', lambda: None)


def test_episode_training_loading_order_and_versions(tmp_path, monkeypatch):
    import omi_hil_rl.hil.alternating as module
    config = HILConfig(review='auto')
    transport = FakeTransport(config, success_step=2)
    phases = []
    class Runner(Alternating):
        def load(self, expected=None):
            self.version = 0 if expected is None else expected
            phases.append(('load', self.version))
        def action(self, observation):
            phases.append(('act', self.version))
            return np.zeros(6, np.float32)
    def worker(*args):
        manifests = list(tmp_path.glob('episodes/*/ready.json'))
        assert manifests and transport.stops > 0
        phases.append(('train', len(manifests)))
    monkeypatch.setattr(module, 'wait_worker', worker)
    runner = Runner(tmp_path, config, transport, updates=2, device='cpu', policy=True)
    runner.run_episodes(2)
    assert phases == [('load', 0), ('act', 0), ('act', 0), ('train', 1),
                      ('load', 2), ('act', 2), ('act', 2), ('train', 2), ('load', 4)]
    assert json.loads((tmp_path/'alternating_state.json').read_text())['phase'] == 'CLOSED'
    assert sorted(json.loads(p.read_text())['policy_version'] for p in tmp_path.glob('episodes/*/ready.json')) == [0, 2]
    assert len(list((tmp_path/'tasks').glob('*.json'))) == 2


def test_failed_training_never_restarts_episode(tmp_path, monkeypatch):
    import omi_hil_rl.hil.alternating as module
    config = HILConfig(review='auto')
    transport = FakeTransport(config, success_step=1)
    runner = Alternating(tmp_path, config, transport, device='cpu', policy=True)
    runner.load = lambda expected=None: setattr(runner, 'version', 0)
    runner.action = lambda obs: np.zeros(6, np.float32)
    def fail(*args):
        raise RuntimeError('training failed')
    monkeypatch.setattr(module, 'wait_worker', fail)
    with pytest.raises(RuntimeError, match='training failed'):
        runner.run_episodes(3)
    assert len(list(tmp_path.glob('episodes/*/ready.json'))) == 1
    assert json.loads((tmp_path/'alternating_state.json').read_text())['phase'] == 'PAUSED'
    with pytest.raises(ValueError, match='ambiguous'):
        runner.run_episodes(3)


def test_ready_without_task_cannot_be_silently_skipped(tmp_path):
    directory = tmp_path/'episodes'/'one'
    directory.mkdir(parents=True)
    atomic_json(directory/'ready.json', dict(episode='one'))
    runner = Alternating(tmp_path, HILConfig(), FakeTransport(), device='cpu')
    with pytest.raises(ValueError, match='no completed training task'):
        runner.run_episodes(1)


def test_actual_subprocess_training_replay_and_policy_reload(tmp_path):
    import torch
    from dataclasses import asdict
    from omi_hil_rl.hil.collect_episodes import collect
    from omi_hil_rl.hil.exchange import publish, read_episode
    from omi_hil_rl.hil.networks import SAC
    from omi_hil_rl.training.transition_replay import TransitionReplay
    torch.set_num_threads(1)
    config = HILConfig(review='auto')
    class Human(FakeTransport):
        def interact(self, *args):
            result = super().interact(*args)
            result.source = 'human'
            return result
    seed = tmp_path/'seed'
    manifest, = collect(seed, config, Human(config, success_step=1), episodes=1)
    directory = seed/'episodes'/manifest['episode']
    run = tmp_path/'run'
    run.mkdir()
    agent = SAC(dict(encoder='synthetic-test'), config.replay_contract(), device='cpu')
    publish(run, agent)
    atomic_json(run/'config.json', asdict(config))
    atomic_json(run/'dataset.json', dict(episodes=[dict(path=str(directory), manifest=manifest)]))
    replay = TransitionReplay(run/'replay', config.replay_contract(), 16, prefetch=False)
    for record in read_episode(directory, manifest):
        replay.append(record, origin='online')
    replay.close()
    runner = Alternating(run, config, FakeTransport(config, success_step=1),
                         updates=2, batch_size=2, device='cpu', policy=True)
    runner.run_episodes(2)
    checkpoint = torch.load(run/'learner.pt', weights_only=True)
    assert checkpoint['updates'] == runner.version == 4
    replay = TransitionReplay.reopen(run/'replay', expected_contract=config.replay_contract(), prefetch=False)
    assert replay.buffer.size() == 3
    replay.close()
    assert len(list(run.glob('episodes/*/imported.json'))) == 2
