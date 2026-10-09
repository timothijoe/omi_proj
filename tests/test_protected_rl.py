from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import import_ready
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.hil.periodic_control import PeriodicAudit
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.training.transition_replay import TransitionReplay
from omi_hil_rl.hil.periodic_replay import eligibility


def batch():
    obs = {k: torch.as_tensor(v)[None] for k, v in FakeTransport()._observation().items()}
    return SimpleNamespace(observations=obs, next_observations=obs, actions=torch.ones(1, 6)*.2,
                           rewards=torch.ones(1, 1), dones=torch.zeros(1, 1))


def test_bc_warmup_exact_and_resumable():
    torch.set_num_threads(1)
    contract = HILConfig().replay_contract()
    bc = SAC({'encoder': 'synthetic-test'}, contract)
    agent = SAC(bc.recipe, contract, freeze_encoder=True, critic_warmup_updates=2, bc_weight=10.,
                actor_learning_rate=1e-5)
    agent.initialize_bc(bc.checkpoint(), provenance={'bc_version': 42})
    original = deepcopy(agent.actor.state_dict())
    target = deepcopy(agent.critic.heads.state_dict())
    b = batch()
    for _ in range(2):
        metrics = agent.update(b, b)
        assert metrics['critic_warmup'] and metrics['bc_reference_max_abs'] == 0
    assert all(torch.equal(v, original[k]) for k, v in agent.actor.state_dict().items())
    assert any(not torch.equal(v, target[k]) for k, v in agent.critic.heads.state_dict().items())
    restored = SAC.restore(deepcopy(agent.checkpoint()), expected_contract=contract)
    assert restored.bc_provenance == {'bc_version': 42}
    assert not any(p.requires_grad for p in restored.actor.encoder.parameters())
    restored.update(b, b)
    metrics = restored.update(b, b)
    assert 'bc_loss' in metrics and not metrics['critic_warmup']
    assert any(not torch.equal(v, original[k]) for k, v in restored.actor.state_dict().items())
    assert all(torch.equal(v, original['encoder.'+k]) for k, v in restored.actor.encoder.state_dict().items())
    assert all(torch.equal(v, original[k]) for k, v in restored.bc_reference.state_dict().items())
    # Missing anchors fail before any optimizer mutation.
    restored.update(b, b)
    with pytest.raises(ValueError, match='human batch'):
        restored.update(b)
    assert restored.updates == 5


@pytest.mark.parametrize('gap', [None, 1, 2])
def test_periodic_background_to_replay_and_learner(tmp_path, gap):
    config = HILConfig(wrist_camera='required')
    obs = FakeTransport()._observation()
    obs['history_mask'][:] = 1
    obs['camera_mask'][:] = 1
    action = np.full(6, .2, np.float32)
    wire = output_action(config.physical_action(action), config.sdk_convention)
    audit = PeriodicAudit(tmp_path, 'source', config.replay_contract(), 7, training=True)
    for i in range(3):
        stamp = 1_000_000_000+i*100_000_000
        tick = dict(command_id=str(i), action_source='human', gate='human', command_trace={},
                    observation_present=True, observation_reference_ns=stamp, command_send_ns=stamp+1_000_000,
                    eef_receive_ns=stamp-1_000_000,
                    normalized_action=action.tolist(), wire_action=wire)
        audit.submit('tick', (tick, obs))
        if i != gap:
            audit.submit('receipt', dict(command_id=str(i), accepted=True, finished=False, status='queue_accepted',
                timestamp_ns=stamp+2_000_000, wire_action=wire, arm='A', delta_frame='base',
                action_source='human', control_mode='velocity_hold', nominal_duration_s=.1))
    boundary = (dict(observation_present=True, observation_reference_ns=1_300_000_000,
                     eef_receive_ns=1_299_000_000,
                     command_send_ns=1_301_000_000), obs)
    result = audit.finish(boundary, dict(episode='source', policy_version=7, success=True, reason='success'))
    assert result['training_ready'] and result['transitions'] == (3 if gap is None else 2)
    assert len(result['segments']) == (2 if gap == 1 else 1)
    assert result['success_label_recorded'] == (gap != 2)
    replay = TransitionReplay(tmp_path/'replay', config.replay_contract(), 8, prefetch=False)
    try:
        import_ready(tmp_path, replay)
        assert replay.buffer.size() == result['transitions']
        imported = list(tmp_path.glob('episodes/*/ready.json'))
        assert sum(json.loads(p.read_text())['episode_success'] for p in imported) == int(gap != 2)
        agent = SAC({'encoder': 'synthetic-test'}, config.replay_contract(), freeze_encoder=True,
                    critic_warmup_updates=2)
        metrics = agent.update(replay.buffer.sample(2))
        assert np.isfinite(metrics['critic_loss'])
    finally:
        replay.close()


def test_abnormal_periodic_end_never_enters_replay(tmp_path):
    config = HILConfig()
    audit = PeriodicAudit(tmp_path, 'interrupted', config.replay_contract(), 0, training=True)
    result = audit.finish(None, dict(episode='interrupted', success=False, reason='interrupted'))
    assert not result['training_ready']
    assert not list(tmp_path.glob('episodes/*/ready.json'))


def test_interval_rejects_interruption_late_receipt_and_wrong_label():
    tick = dict(command_id='c', observation_present=True, observation_reference_ns=1_000_000_000,
                command_send_ns=1_001_000_000, wire_action=[0.]*6, gate='policy', action_source='policy')
    nxt = dict(observation_present=True, observation_reference_ns=1_100_000_000, command_send_ns=1_101_000_000,
               eef_receive_ns=1_099_000_000)
    receipt = dict(command_id='c', accepted=True, status='queue_accepted', timestamp_ns=1_002_000_000,
        wire_action=[0.]*6, arm='A', delta_frame='base', control_mode='velocity_hold',
        action_source='policy', nominal_duration_s=.1)
    assert eligibility(tick, nxt, [receipt], []) == 'valid'
    assert eligibility(tick, dict(nxt, eef_receive_ns=1_000_000_000), [receipt], []) == 'missing_causal_eef'
    assert eligibility(tick, nxt, [receipt], [1_050_000_000]) == 'interrupted_command'
    assert eligibility(tick, nxt, [dict(receipt, timestamp_ns=1_099_000_000)], []) == 'acceptance_too_late'
    assert eligibility(tick, nxt, [dict(receipt, action_source='human')], []) == 'receipt_contract'
    assert eligibility(tick, nxt, [dict(receipt, nominal_duration_s=float('nan'))], []) == 'receipt_contract'
    rejected = dict(receipt, accepted=False, status='queue_replaced', timestamp_ns=1_050_000_000)
    assert eligibility(tick, nxt, [receipt, rejected], []) == 'receiver_rejected_interval'
    assert eligibility(tick, nxt, [receipt, dict(rejected, accepted=True, status='queue_cancelled')], []) == 'receiver_rejected_interval'
    terminal = dict(nxt, terminal_success_stop_ns=1_040_000_000)
    cancelled = dict(rejected, accepted=True, status='queue_cancelled')
    assert eligibility(tick, terminal, [receipt, cancelled], []) == 'valid'
    assert eligibility(tick, dict(terminal, terminal_success_stop_ns=1_001_000_000), [receipt], []) == 'terminal_stop_before_acceptance'


def test_prepare_new_bc_rl_seed(tmp_path):
    from omi_hil_rl.hil.exchange import EpisodeSpool, atomic_json, atomic_torch
    from omi_hil_rl.hil.prepare_bc_rl import prepare
    from omi_hil_rl.training.eef_bc_data import sha256
    config = HILConfig()
    bc = tmp_path/'bc'
    bc.mkdir()
    agent = SAC({'encoder': 'synthetic-test'}, config.replay_contract())
    state = agent.checkpoint()
    state['training_method'] = 'behavior_cloning'
    atomic_torch(bc/'actor.pt', state)
    atomic_json(bc/'config.json', config.replay_contract()['config'])
    spool = EpisodeSpool(tmp_path/'collection', 'seed', config.replay_contract())
    obs = FakeTransport()._observation()
    spool.append(obs, obs, 1., True, False, dict(episode='seed', step=0, executed_action=np.zeros(6),
        observation_time_ns=1, next_observation_time_ns=2, action_source='human', command_status='ok'))
    manifest = spool.finish(True, reason='success')
    entry = dict(path=str(spool.directory), manifest=manifest, manifest_sha256=sha256(spool.directory/'ready.json'),
                 sample_sha256=[sha256(spool.directory/'000000.npz')], split='training')
    atomic_json(bc/'dataset.json', dict(episodes=[entry]))
    destination = tmp_path/'rl'
    report = prepare(bc, destination, capacity=4, warmup=2)
    assert report['samples'] == 1 and report['initial_actor_exact']
    assert json.loads((destination/'async_session.json').read_text())['control_mode'] == 'periodic_training_v1'
    restored = SAC.restore(torch.load(destination/'learner.pt', weights_only=True))
    assert restored.freeze_encoder and restored.critic_warmup_updates == 2
    np.testing.assert_array_equal(restored.act(obs, True), agent.act(obs, True))
    with pytest.raises(ValueError, match='new RL run'):
        prepare(bc, destination)


def test_periodic_success_stops_then_records_terminal_state_before_reset(tmp_path, monkeypatch, capsys):
    import omi_hil_rl.hil.periodic_control as module
    now = [100.]
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    config = HILConfig(episode_seconds=3., wrist_camera='required')
    obs = FakeTransport()._observation()
    obs['history_mask'][:] = 1
    obs['camera_mask'][:] = 1
    sent, finished = [], []
    class Transport:
        connected = True
        allow_manual_reset = False
        events = set()
        event_times = {}
        latest = None
        latest_eef_time = 0
        last_command_trace = {}
        pad = SimpleNamespace(buttons={}, axes={})
        consumed = None
        def take(self):
            if self.latest[1] == self.consumed:
                return None
            self.consumed = self.latest[1]
            return (*self.latest, np.ones(6)*.1, 0.)
        node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(now[0]*1e9))))
        def wait_start(self): return now[0]
        def start_episode(self): pass
        def idle_tick(self): pass
        def _pump(self):
            now[0] += .01
            stamp = int(now[0]*10)*100_000_000
            self.latest, self.latest_eef_time = (obs, stamp), stamp-1_000_000
            if len(sent) >= 12 and now[0]-sent[-1][0] >= .04:
                self.events.add('success')
                self.event_times.setdefault('success', now[0])
            if getattr(self, 'pending', None) is not None:
                receipt, self.pending = self.pending, None
                self.receipt_hook(receipt)
        def _publish(self, action, command_id):
            wire = output_action(action, config.sdk_convention)
            sent.append((now[0], command_id))
            self.pending = dict(command_id=command_id, accepted=True, finished=False, status='queue_accepted',
                timestamp_ns=int(now[0]*1e9)+1, wire_action=wire, arm='A', delta_frame='base',
                action_source='policy', control_mode='velocity_hold', nominal_duration_s=.1)
            self.last_receipt = self.pending
            return wire
        def stop(self):
            if getattr(self, 'receipt_hook', None) and hasattr(self, 'last_receipt'):
                self.receipt_hook(dict(self.last_receipt, status='queue_cancelled', finished=True,
                                       timestamp_ns=int(now[0]*1e9)+1))
    tr = Transport()
    tr.policy_pipeline = SimpleNamespace(take=tr.take)
    tr.config = config
    actor = SimpleNamespace(transport=tr, config=config, run=tmp_path, version=0, load=lambda: None,
                            close_pipeline=lambda: None, state=lambda *a, **kw: None, finished=finished.append)
    module.run_periodic(actor, 1, training=True)
    report = json.loads(next(tmp_path.glob('periodic_episodes/*/audit.json')).read_text())
    assert report['success_label_recorded'] and report['training_ready']
    assert len(finished) == 1
    assert max(np.diff([t for t, _ in sent])) < .12
    printed = capsys.readouterr().out
    assert 'RL 回合已开始' in printed
    assert '正在保存 RL 回合' in printed
    assert '本地保存完成' in printed and '训练片段待 Learner 异步导入' in printed


@pytest.mark.skipif(not torch.cuda.is_available(), reason='CUDA required for real BC protection probe')
def test_real_bc_cuda_warmup_and_anchored_update():
    from pathlib import Path
    from omi_hil_rl.hil.exchange import read_episode
    root = Path('local/bc_episodes/all8_coarse_fine_eval_01')
    if not root.exists():
        pytest.skip('local BC fixture not installed')
    torch.set_num_threads(2)
    state = torch.load(root/'actor.pt', map_location='cpu', weights_only=True)
    agent = SAC(state['recipe'], state['contract'], device='cuda', freeze_encoder=True,
                critic_warmup_updates=2, bc_weight=10., actor_learning_rate=1e-5)
    agent.initialize_bc(state)
    entry = json.loads((root/'dataset.json').read_text())['episodes'][0]
    record = next(read_episode(entry['path'], entry['manifest']))
    b = SimpleNamespace(observations={k: torch.as_tensor(v)[None] for k, v in record['observation'].items()},
        next_observations={k: torch.as_tensor(v)[None] for k, v in record['next_observation'].items()},
        actions=torch.as_tensor(record['executed_action'])[None], rewards=torch.zeros(1, 1), dones=torch.zeros(1, 1))
    before = agent.act(record['observation'], True)
    for _ in range(2):
        result = agent.update(b, b)
        assert result['bc_reference_max_abs'] == 0
    np.testing.assert_array_equal(before, agent.act(record['observation'], True))
    agent.update(b, b)
    result = agent.update(b, b)
    assert np.isfinite(result['bc_loss']) and result['bc_reference_max_abs'] > 0
    assert all(torch.equal(v.cpu(), state['actor']['encoder.'+k])
               for k, v in agent.actor.encoder.state_dict().items())
    print('REAL_BC_PROTECTION_PROBE:', result)
