from copy import deepcopy
import json

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import EpisodeSpool, atomic_json, atomic_torch, import_ready, publish
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.training.dual_replay import DualTransitionReplay, open_replay
from omi_hil_rl.training.transition_replay import CONTRACT_KEYS, TransitionReplay
from omi_hil_rl.training.eef_bc_data import sha256


def record(episode='seed', step=0, source='human', value=.1):
    contract = HILConfig().replay_contract()
    obs = FakeTransport()._observation()
    return dict({k: contract[k] for k in CONTRACT_KEYS}, episode=episode, step=step,
        action_source=source, observation_time_ns=1+step*100, next_observation_time_ns=101+step*100,
        observation=obs, next_observation=obs, executed_action=np.full(6, value, np.float32),
        reward=0., terminated=False, truncated=True, episode_success=False)


def create(path, seed_capacity=2, online_capacity=4, intervention_capacity=2):
    return DualTransitionReplay(path, HILConfig().replay_contract(), seed_capacity=seed_capacity,
        online_capacity=online_capacity, intervention_capacity=intervention_capacity)


def test_independent_capacity_preserves_seed_and_routes_interventions(tmp_path):
    replay = create(tmp_path/'replay')
    replay.append_seed(record())
    replay.seal_seed()
    with pytest.raises(ValueError, match='unsealed'):
        replay.append_seed(record())
    for i in range(10):
        replay.append(record('human', i, value=.2))
        replay.append(record('robot', i, source='policy', value=.8))
    counts = replay.stream_counts()
    assert counts['initial_demonstration'] == 1
    assert counts['online'] == 4 and counts['intervention'] == 2 and counts['demonstration'] == 3
    np.testing.assert_array_equal(replay.pools['seed'].buffer.actions[0, 0], record()['executed_action'])
    assert all(replay.pools['interventions'].metadata(i)['action_source'] == 'human' for i in range(2))
    assert (replay.sample_human(100).actions.numpy() < .3).all()
    replay.close()
    reopened = open_replay(tmp_path/'replay', expected_contract=HILConfig().replay_contract())
    assert reopened.stream_counts() == counts and reopened.seed_sealed
    reopened.close()


def test_exact_half_sampling_and_empty_pool_no_silent_fallback(tmp_path):
    replay = create(tmp_path/'r')
    try:
        replay.append_seed(record(value=.1))
        replay.seal_seed()
        with pytest.raises(RuntimeError, match='online buffer empty'):
            replay.sample(10)
        replay.append(record('policy', source='policy', value=.8))
        for _ in range(5):
            actions = replay.sample(20).actions[:, 0].numpy()
            assert np.count_nonzero(actions < .5) == 10
            assert np.count_nonzero(actions > .5) == 10
        with pytest.raises(ValueError, match='even'):
            replay.sample(3)
    finally:
        replay.close()


def spool(run):
    c = HILConfig().replay_contract()
    writer = EpisodeSpool(run, 'episode', c)
    for i, source in enumerate(['human', 'policy']):
        r = record('episode', i, source)
        writer.append(r['observation'], r['next_observation'], 0., False, i == 1,
            dict(r, command_status='accepted'))
    return writer.finish(True, reason='timeout')


def test_import_idempotent_and_recover_checkpoint_before_import_receipt(tmp_path, monkeypatch):
    run = tmp_path/'run'
    spool(run)
    replay = create(run/'replay')
    replay.append_seed(record())
    replay.seal_seed()
    import omi_hil_rl.training.dual_replay as module
    original = module.atomic
    def crash(path, value):
        if path.name == 'imported.json':
            raise OSError('receipt interrupted after clean replay commit')
        original(path, value)
    monkeypatch.setattr(module, 'atomic', crash)
    with pytest.raises(OSError):
        import_ready(run, replay)
    replay.close()
    monkeypatch.setattr(module, 'atomic', original)
    replay = open_replay(run/'replay')
    assert import_ready(run, replay) == 0
    assert replay.stream_counts()['online'] == 2
    assert replay.stream_counts()['intervention'] == 1
    assert (run/'episodes/episode/imported.json').exists()
    replay.close()


def test_partial_dual_write_is_not_blessed_by_close(tmp_path, monkeypatch):
    replay = create(tmp_path/'r')
    replay.append_seed(record())
    replay.seal_seed()
    def fail(*a, **kw):
        raise OSError('simulated intervention disk failure')
    monkeypatch.setattr(replay.pools['interventions'], 'append', fail)
    with pytest.raises(OSError):
        replay.append(record('new'))
    replay.close()
    assert not json.loads((tmp_path/'r/manifest.json').read_text())['clean']
    with pytest.raises(ValueError, match='clean checkpoint'):
        open_replay(tmp_path/'r')


def test_seed_overflow_and_second_writer_refused(tmp_path):
    replay = create(tmp_path/'r', seed_capacity=1)
    try:
        replay.append_seed(record())
        with pytest.raises(ValueError, match='capacity'):
            replay.append_seed(record(step=1))
        with pytest.raises(RuntimeError, match='writer'):
            open_replay(tmp_path/'r')
    finally:
        replay.close()


def test_critic_warmup_then_wait_for_genuine_online(tmp_path):
    from omi_hil_rl.hil.learner import run_learner
    torch.set_num_threads(1)
    config = HILConfig()
    replay = create(tmp_path/'replay')
    replay.append_seed(record())
    replay.seal_seed()
    replay.close()
    agent = SAC({'encoder': 'synthetic-test'}, config.replay_contract(), freeze_encoder=True,
                critic_warmup_updates=2, bc_weight=10.)
    agent.initialize_bc(agent.checkpoint())
    initial = deepcopy(agent.actor.state_dict())
    publish(tmp_path, agent)
    run_learner(tmp_path, config, batch_size=2, updates=2, min_online=1, wait_seconds=10)
    result = torch.load(tmp_path/'learner.pt', weights_only=True)
    assert all(torch.equal(v, initial[k]) for k, v in result['actor'].items())
    with pytest.raises(TimeoutError):
        run_learner(tmp_path, config, batch_size=2, updates=1, min_online=1, wait_seconds=.1)
    assert torch.load(tmp_path/'learner.pt', weights_only=True)['updates'] == 2
    spool(tmp_path)
    result = run_learner(tmp_path, config, batch_size=2, updates=2, min_online=1, wait_seconds=10)
    assert result['updates'] == 4 and result['streams']['online'] == 2


def test_legacy_migration_preserves_weights_and_routes_by_provenance(tmp_path):
    from omi_hil_rl.hil.migrate_dual_replay import migrate
    source = tmp_path/'source'
    source.mkdir()
    config = HILConfig()
    c = config.replay_contract()
    seed = EpisodeSpool(tmp_path/'collection', 'seed', c)
    r = record()
    seed.append(r['observation'], r['next_observation'], 0., False, True, dict(r, command_status='ok'))
    m = seed.finish(True, reason='timeout')
    atomic_json(source/'dataset.json', dict(episodes=[dict(path=str(seed.directory), manifest=m, split='training',
        manifest_sha256=sha256(seed.directory/'ready.json'), sample_sha256=[sha256(seed.directory/'000000.npz')])]))
    agent = SAC({'encoder': 'synthetic-test'}, c)
    publish(source, agent)
    for name, data in [('config', c['config']), ('recipe', agent.recipe), ('async_session', dict(mode='async_hil_v1', contract=c))]:
        atomic_json(source/(name+'.json'), data)
    old = TransitionReplay(source/'replay', c, 8, prefetch=False)
    old.append(r)
    old.append(record('online_human', source='human', value=.2))
    old.append(record('online_policy', source='policy', value=.8))
    old.close()
    output = tmp_path/'destination'
    report = migrate(source, output, intervention_capacity=2)
    assert report['restored_initial_samples'] == 1 and report['removed_seed_from_online'] == 1
    assert report['streams']['online'] == 2 and report['streams']['intervention'] == 1
    assert sha256(source/'actor.pt') == sha256(output/'actor.pt')
    assert sha256(source/'learner.pt') == sha256(output/'learner.pt')
    replay = open_replay(output/'replay')
    assert replay.stream_counts()['initial_demonstration'] == 1
    replay.close()
    with pytest.raises(ValueError, match='new destination'):
        migrate(source, output)
