"""Asynchronous training lifecycle without robot output."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.async_training import AsyncActor, LearnerProcess, initialize
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.collect_episodes import collect
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import atomic_json, publish, read_episode
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.training.transition_replay import TransitionReplay


def test_async_transport_routes_home_and_gripper_without_robot(monkeypatch):
    from omi_hil_rl.hil.alternating import make_transport
    from omi_hil_rl.hil.ros_transport import RosTransport
    from omi_hil_rl.real import linux_gamepad, receiver_preflight
    rclpy = ModuleType('rclpy')
    rclpy.__path__ = []
    qos = ModuleType('rclpy.qos')
    qos.QoSProfile = lambda **kwargs: kwargs
    qos.ReliabilityPolicy = SimpleNamespace(RELIABLE='reliable')
    std_msgs = ModuleType('std_msgs')
    std_msgs.__path__ = []
    msg = ModuleType('std_msgs.msg')
    msg.Float64MultiArray = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, 'rclpy', rclpy)
    monkeypatch.setitem(sys.modules, 'rclpy.qos', qos)
    monkeypatch.setitem(sys.modules, 'std_msgs', std_msgs)
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', msg)
    monkeypatch.setattr(receiver_preflight, 'inspect_receiver', lambda **kwargs:
        dict(manual_topic='/omi/action/manual_decision'))
    class Pad:
        button_map = [304, 305, 307, 308, 311, 314, 315]
        def __init__(self, path): pass
        def poll(self): return True
        def close(self): pass
    monkeypatch.setattr(linux_gamepad, 'LinuxGamepad', Pad)
    published = []
    class Node:
        def count_publishers(self, topic): return 1
        def create_publisher(self, *args): return SimpleNamespace(publish=lambda value: published.append(value))
    constructed, routed = [], []
    def fake_init(self, config, contract, **kwargs):
        constructed.append(kwargs)
        self.node = Node()
        self.topic = '/omi/action/decision'
        self.publisher = SimpleNamespace(publish=lambda value: published.append(value))
        self.last_owner = None
        self.gripper = kwargs['gripper']
    def fake_publish(self, action, command_id=None, **kwargs):
        routed.append((self.topic, command_id, kwargs))
    monkeypatch.setattr(RosTransport, '__init__', fake_init)
    monkeypatch.setattr(RosTransport, '_publish', fake_publish)
    started = []
    gripper = SimpleNamespace(args=SimpleNamespace(gripper_server='fake'), start=lambda: started.append(True))
    args = SimpleNamespace(gamepad='/dev/input/js0', rgb_max_age_ms=500., home_button_code=314,
                           gripper=gripper, log_buttons=True)
    transport = make_transport(HILConfig(transport='ros', review='auto'), dict(base_contract={}), args)
    assert constructed[0]['home_button_code'] == 314
    assert constructed[0]['gripper'] is gripper and started == [True]
    assert transport.log_buttons
    transport._publish(np.zeros(6), convention='sdk-base-aligned', source='human_home')
    transport.last_owner = 'policy'
    transport._publish(np.zeros(6), 'hil:policy')
    transport.last_owner = 'human'
    transport._publish(np.zeros(6), 'hil:human')
    assert routed == [
        ('/omi/action/manual_decision', None, dict(convention='sdk-base-aligned', source='human_home')),
        ('/omi/action/decision', 'hil:policy', {}),
        ('/omi/action/manual_decision', 'hil:human', {}),
    ]


def test_interpreter_keeps_virtual_environment_symlink(tmp_path):
    from omi_hil_rl.hil.shutdown import interpreter_path
    python = tmp_path/'venv/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    assert interpreter_path(python) == str(python)
    assert interpreter_path(python) != str(python.resolve())


@pytest.mark.parametrize('fault_first', [False, True])
def test_supervisor_ctrl_c_closes_all_owned_components(tmp_path, monkeypatch, fault_first):
    import signal
    import omi_hil_rl.hil.async_training as module
    from omi_hil_rl.hil.networks import VERSION
    config = HILConfig(transport='ros', review='auto', wrist_camera='required')
    atomic_json(tmp_path/'config.json', asdict(config))
    atomic_json(tmp_path/'async_session.json', dict(mode='async_hil_v1', contract=config.replay_contract()))
    torch.save(dict(version=VERSION, contract=config.replay_contract(), recipe={}), tmp_path/'actor.pt')
    events = []
    class Transport:
        def stop(self): events.append('stop')
        def close(self): events.append('transport_closed')
        def idle_tick(self): signal.raise_signal(signal.SIGINT)
    class Worker:
        def __init__(self, *args): pass
        def start(self): events.append('learner_started')
        def check(self): pass
        def close(self, *args):
            events.append('learner_reaped')
            return True  # Forced shutdown still MUST exit, never re-enter PAUSED.
    class Actor:
        def __init__(self, *args, **kwargs): pass
        def run_episodes(self, *args):
            if fault_first:
                raise RuntimeError('training fault')
            signal.raise_signal(signal.SIGINT)
        def state(self, phase, **kwargs): events.append(phase)
    controls = []
    def transport_with_controls(config, recipe, args):
        controls.append((args.home_button_code, args.gripper.args.gripper_server,
                         args.gripper.args.gripper_calibration, args.log_buttons))
        return Transport()
    monkeypatch.setattr(module, 'make_transport', transport_with_controls)
    monkeypatch.setattr(module, 'LearnerProcess', Worker)
    monkeypatch.setattr(module, 'AsyncActor', Actor)
    monkeypatch.setattr(sys, 'argv', ['async_training', '--run', str(tmp_path), '--execute',
                                    '--learner-python', sys.executable])
    module.main()
    assert 'learner_started' in events
    assert 'learner_reaped' in events and 'transport_closed' in events
    assert events[-1] == 'CLOSED'
    assert ('PAUSED' in events) == fault_first
    assert controls == [(314, '192.168.14.11:55551',
                         Path(__file__).resolve().parents[1]/'tutorials/gripper_limits.json', True)]


def seed_run(tmp_path):
    torch.set_num_threads(1)
    config = HILConfig(review='auto')
    class Human(FakeTransport):
        def interact(self, *args):
            result = super().interact(*args)
            result.source = 'human'
            return result
    source = tmp_path/'source'
    manifest, = collect(source, config, Human(config, success_step=1), episodes=1)
    directory = source/'episodes'/manifest['episode']
    seed = tmp_path/'seed'
    seed.mkdir()
    agent = SAC(dict(encoder='synthetic-test'), config.replay_contract(), device='cpu')
    publish(seed, agent)
    atomic_json(seed/'recipe.json', agent.recipe)
    atomic_json(seed/'config.json', asdict(config))
    atomic_json(seed/'dataset.json', dict(episodes=[dict(path=str(directory), manifest=manifest)]))
    replay = TransitionReplay(seed/'replay', config.replay_contract(), 64, prefetch=False)
    for record in read_episode(directory, manifest):
        replay.append(record, origin='online')
    replay.close()
    return config, seed, agent


def test_reload_every_ten_complete_episodes_not_steps(tmp_path):
    config = HILConfig(review='auto')
    transport = FakeTransport(config, success_step=2)
    loads = []
    class Actor(AsyncActor):
        def load(self, expected=None):
            loads.append(self.completed)
            self.last_reload_check = self.completed
            self.version = self.completed
        def action(self, obs):
            return np.zeros(6, np.float32)
    actor = Actor(tmp_path, config, transport, device='cpu', policy=True)
    actor.run_episodes(21)
    assert loads == [0, 10, 20]
    assert actor.completed == 21
    for path in tmp_path.glob('episodes/*/ready.json'):
        manifest = json.loads(path.read_text())
        records = list(read_episode(path.parent, manifest))
        assert len(records) == 2
        assert all(r['policy_version'] == manifest['policy_version'] for r in records)


def test_rejected_checkpoint_keeps_old_policy_and_recipe(tmp_path):
    config, seed, agent = seed_run(tmp_path)
    actor = AsyncActor(seed, config, FakeTransport(config), device='cpu')
    actor.load()
    original = actor.actor
    state = torch.load(seed/'actor.pt', weights_only=True)
    state['recipe']['different_normalization'] = True
    state['updates'] = 1
    from omi_hil_rl.hil.exchange import atomic_torch
    atomic_torch(seed/'actor.pt', state)
    actor.load()
    assert actor.actor is original and actor.version == 0
    assert 'recipe' in actor.last_reload_error


def test_clone_is_independent_and_dirty_seed_rejected(tmp_path):
    config, seed, agent = seed_run(tmp_path)
    run = tmp_path/'run'
    initialize(seed, run)
    assert (seed/'replay/actions.npy').stat().st_ino != (run/'replay/actions.npy').stat().st_ino
    assert json.loads((run/'async_session.json').read_text())['contract'] == config.replay_contract()
    with pytest.raises(ValueError, match='new destination'):
        initialize(seed, run)
    manifest = json.loads((seed/'replay/manifest.json').read_text())
    manifest['clean'] = False
    atomic_json(seed/'replay/manifest.json', manifest)
    with pytest.raises(ValueError, match='dirty'):
        initialize(seed, tmp_path/'dirty')


def test_learner_child_is_reaped_even_when_ignoring_sigint(tmp_path):
    ready = tmp_path/'ready'
    command = [sys.executable, '-c',
               'import signal,time,pathlib; signal.signal(signal.SIGINT,signal.SIG_IGN); '
               f'pathlib.Path({str(ready)!r}).touch(); time.sleep(30)']
    worker = LearnerProcess(command, tmp_path/'learner.log')
    worker.start()
    try:
        end = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < end:
            time.sleep(.01)
        assert ready.exists()
        assert worker.close(timeout=.05)
        assert worker.child.poll() is not None and worker.stream.closed
    finally:
        worker.close(timeout=.05)


def test_real_concurrent_learner_and_actor_resume_without_duplicate_import(tmp_path):
    config, seed, agent = seed_run(tmp_path)
    run = tmp_path/'run'
    initialize(seed, run)
    command = [sys.executable, '-m', 'omi_hil_rl.hil.learner', '--run', str(run),
               '--config', str(run/'config.json'), '--batch-size', '2', '--publish-every', '2',
               '--update-delay', '.01', '--device', 'cpu']
    worker = LearnerProcess(command, run/'learner.log')
    worker.start()
    class SlowTransport(FakeTransport):
        def interact(self, *args):
            time.sleep(.015)
            worker.check()
            return super().interact(*args)
    actor = AsyncActor(run, config, SlowTransport(config, success_step=2),
                       reload_episodes=10, device='cpu', policy=True)
    try:
        # Wait for the real child to train; it remains live THROUGH collection.
        end = time.monotonic()+15
        while not (run/'status.json').exists() and time.monotonic() < end:
            worker.check()
            time.sleep(.02)
        assert (run/'status.json').exists()
        actor.run_episodes(11)
        end = time.monotonic()+15
        while len(list(run.glob('episodes/*/imported.json'))) < 11 and time.monotonic() < end:
            worker.check()
            time.sleep(.02)
        assert len(list(run.glob('episodes/*/imported.json'))) == 11
        worker.check()  # Still training, not paused awaiting another episode.
    finally:
        assert not worker.close(timeout=10)
    state = torch.load(run/'learner.pt', weights_only=True)
    assert state['updates'] > 0 and actor.version > 0
    replay = TransitionReplay.reopen(run/'replay', expected_contract=config.replay_contract(), prefetch=False)
    assert replay.buffer.size() == 23
    replay.close()
    # A fresh process reimports no old episodes and can keep training old data.
    worker = LearnerProcess(command, run/'learner.log')
    worker.start()
    try:
        end = time.monotonic()+15
        while time.monotonic() < end:
            worker.check()
            if json.loads((run/'status.json').read_text()).get('update', 0) > state['updates']:
                break
            time.sleep(.02)
        else:
            pytest.fail('resumed learner did not advance')
    finally:
        assert not worker.close(timeout=10)
    replay = TransitionReplay.reopen(run/'replay', expected_contract=config.replay_contract(), prefetch=False)
    assert replay.buffer.size() == 23
    replay.close()
