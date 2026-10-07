from dataclasses import asdict
import json
import signal
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.bc_rollout import FixedBCActor, prepare, validate_run
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.collect_episodes import collect
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import atomic_json
from omi_hil_rl.hil.networks import Actor, VERSION


def test_bc_prepare_snapshot_and_reject_changed_weights(tmp_path):
    torch.set_num_threads(1)
    config = HILConfig(review='auto')
    source = tmp_path/'source'
    class Human(FakeTransport):
        def interact(self, *args):
            result = super().interact(*args)
            result.source = 'human'
            return result
    manifest, = collect(source, config, Human(config, success_step=1), episodes=1)
    ep = source/'episodes'/manifest['episode']
    recipe = dict(encoder='synthetic-test')
    actor = Actor(recipe)
    state = dict(version=VERSION, recipe=recipe, contract=config.replay_contract(), updates=295,
                 actor=actor.state_dict(), training_method='behavior_cloning')
    torch.save(state, source/'actor.pt')
    atomic_json(source/'dataset.json', dict(episodes=[dict(path=str(ep), manifest=manifest)]))
    output = tmp_path/'rollout'
    prepare(source/'actor.pt', output)
    assert validate_run(output) == config
    assert not (output/'learner.pt').exists()
    assert json.loads((output/'bc_session.json').read_text())['learner_enabled'] is False
    with pytest.raises(ValueError, match='exists'):
        prepare(source/'actor.pt', output)
    state['updates'] = 999
    torch.save(state, output/'actor.pt')
    with pytest.raises(ValueError, match='changed'):
        validate_run(output)


def test_fixed_bc_does_not_reload_at_ten_episodes(tmp_path):
    config = HILConfig(review='auto')
    loads = []
    class Fixed(FixedBCActor):
        def load(self, expected=None):
            loads.append(True)
            self.version = 295
        def action(self, observation):
            return np.zeros(6, np.float32)
    actor = Fixed(tmp_path, config, FakeTransport(config, success_step=1), policy=True, device='cpu')
    actor.run_episodes(11)
    assert len(loads) == 1 and actor.completed == 11
    assert len(list(tmp_path.glob('episodes/*/ready.json'))) == 11
    for path in tmp_path.glob('episodes/*/ready.json'):
        assert json.loads(path.read_text())['policy_version'] == 295


@pytest.mark.parametrize('fault', [False, True])
@pytest.mark.parametrize('control_mode', ['receipt', 'periodic'])
def test_bc_ctrl_c_closes_components_without_learner(tmp_path, monkeypatch, fault, control_mode):
    import omi_hil_rl.hil.bc_rollout as module
    events = []
    class Transport:
        def stop(self): events.append('stop')
        def close(self): events.append('close')
        def idle_tick(self): signal.raise_signal(signal.SIGINT)
    class Fixed:
        def __init__(self, *a, **kw): pass
        def run_episodes(self, count):
            if fault:
                raise RuntimeError('test fault')
            signal.raise_signal(signal.SIGINT)
        def close_pipeline(self): events.append('join')
        def state(self, phase, **kw): events.append(phase)
    atomic_json(tmp_path/'recipe.json', {})
    monkeypatch.setattr(module, 'validate_run', lambda run: HILConfig(transport='ros', review='auto'))
    monkeypatch.setattr(module, 'make_transport', lambda *a: Transport())
    monkeypatch.setattr(module, 'FixedBCActor', Fixed)
    monkeypatch.setattr(module, 'run_periodic', lambda actor, count: actor.run_episodes(count))
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('BC must not spawn learner'))
    monkeypatch.setattr(sys, 'argv', ['bc_rollout', '--output', str(tmp_path), '--resume', '--execute', '--control-mode', control_mode])
    module.main()
    assert events[-1] == 'CLOSED'
    assert events.index('stop') < events.index('join') < events.index('close')
    assert ('PAUSED' in events) == fault


def test_warmup_missing_camera_keeps_manual_reset_and_reports_reason(capsys):
    from omi_hil_rl.hil.ros_transport import RosTransport
    from omi_hil_rl.hil.environment import InteractionUnavailable
    transport = RosTransport.__new__(RosTransport)
    transport.publisher = None
    transport.events = set()
    transport.latest = None
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={311: True})
    transport.runtime = SimpleNamespace(topics={'/omi/wrist/color/image_roi': 'wrist_rgb'},
                                       latest={}, counts={}, rejected={})
    transport.latest_status = {'reason': 'missing_or_stale:wrist_rgb'}
    transport._pump = lambda: time.sleep(.001)
    ticks = []
    transport._manual_reset_tick = lambda: ticks.append(True)
    with pytest.raises(InteractionUnavailable, match='wrist_rgb'):
        transport.observe(time.monotonic()+.02)
    assert ticks
    assert transport.warmup_diagnostics['missing_since_reset'] == ['wrist_rgb']
    assert 'WARMUP_STATUS' in capsys.readouterr().out


def test_warmup_stop_button_aborts_without_waiting_for_camera():
    from omi_hil_rl.hil.ros_transport import RosTransport
    from omi_hil_rl.hil.environment import InteractionUnavailable
    transport = RosTransport.__new__(RosTransport)
    transport.publisher = None
    transport.events = {'manual_stop'}
    transport._pump = lambda: None
    with pytest.raises(InteractionUnavailable, match='operator ended'):
        transport.observe(time.monotonic()+5)
