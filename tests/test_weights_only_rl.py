import json
from pathlib import Path

import pytest
import torch

from omi_hil_rl.hil.async_training import AsyncActor, checkpoint_probe
from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import atomic_json, atomic_torch
from omi_hil_rl.hil.learner import run_learner
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.hil.prepare_bc_rl import prepare
from omi_hil_rl.training.dual_replay import open_replay
from test_cached_replay import episode


@pytest.mark.parametrize('episode_seconds', [None, 30.])
def test_weights_only_needs_no_old_dataset_loads_actor_and_trains_only_after_new_human_data(tmp_path, episode_seconds):
    torch.set_num_threads(1)
    config=HILConfig(review='auto'); contract=config.replay_contract()
    original=SAC({'encoder':'synthetic-test'},contract)
    state=original.checkpoint(); state['training_method']='behavior_cloning'
    bc=tmp_path/'bc';bc.mkdir()
    atomic_torch(bc/'actor.pt',state);atomic_json(bc/'config.json',contract['config'])
    # No old dataset.json or demonstration files exist at all.
    run=tmp_path/'run'
    report=prepare(bc,run,weights_only=True,replay_backend='cached',warmup=2,
                   cache_target_gib=.06,cache_limit_gib=.12,episode_seconds=episode_seconds)
    config=HILConfig(**json.loads((run/'config.json').read_text()));contract=config.replay_contract()
    assert config.episode_seconds==(15. if episode_seconds is None else episode_seconds)
    assert json.loads((bc/'config.json').read_text())['episode_seconds']==15.
    assert json.loads((run/'async_session.json').read_text())['contract']==contract
    assert json.loads((run/'replay/manifest.json').read_text())['contract']==contract
    assert report['samples']==report['episodes']==0 and report['weights_only']
    assert report['initial_actor_exact'] and not any(report['streams'].values())
    assert json.loads((run/'dataset.json').read_text())==dict(episodes=[],training_data_policy='new_session_only')
    assert json.loads((run/'replay/manifest.json').read_text())['sources']==[]
    loaded=torch.load(run/'actor.pt',weights_only=True)
    assert loaded['contract']==contract
    assert torch.load(run/'learner.pt',weights_only=True)['contract']==contract
    assert all(torch.equal(v,loaded['actor'][k]) for k,v in state['actor'].items())
    transport=FakeTransport(config)
    actor=AsyncActor(run,config,transport,device='cpu',policy=True)
    actor.load()
    assert actor.version==0 and actor.last_checkpoint_probe_kind=='contract_zero_numerical_only'
    transport.latest=(transport._observation(),42)
    assert checkpoint_probe(run,config,transport)[0] is transport.latest[0]
    with pytest.raises(TimeoutError):
        run_learner(run,config,batch_size=2,updates=1,wait_seconds=.15)
    assert torch.load(run/'learner.pt',weights_only=True)['updates']==0
    episode(run,'new_policy',contract,sources=('policy','policy'))
    with pytest.raises(TimeoutError):
        run_learner(run,config,batch_size=2,updates=1,wait_seconds=1.)
    assert torch.load(run/'learner.pt',weights_only=True)['updates']==0
    episode(run,'new_human',contract,sources=('human','human'))
    result=run_learner(run,config,batch_size=2,updates=4,wait_seconds=10.)
    assert result['updates']==4
    assert result['streams']['initial_demonstration']==0
    assert result['streams']['online']==4 and result['streams']['demonstration']==2
    replay=open_replay(run/'replay')
    try:
        assert replay.sources==[]
        assert replay.storage_stats()['catalog_seed']==0
        paths=[replay._resolve(r[0]) for r in replay.db.execute('SELECT path FROM records')]
        assert len(paths)==4 and all(p.is_relative_to(run) for p in paths)
    finally:
        replay.close()


@pytest.mark.parametrize('kwargs',[dict(replay_backend='disk'),
                                   dict(replay_backend='cached',recorded_sources=['old'])])
def test_weights_only_rejects_historical_sources_before_creating_run(tmp_path,kwargs):
    run=tmp_path/'run'
    with pytest.raises(ValueError,match='no recorded sources'):
        prepare(tmp_path/'absent_bc',run,weights_only=True,**kwargs)
    assert not run.exists()
