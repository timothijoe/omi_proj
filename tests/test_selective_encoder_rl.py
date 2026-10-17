"""Selective tactile/fusion learning and immutable seed time-limit transfer."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
import torch
from torch import nn

from omi_hil_rl.hil.config import HILConfig, same_contract_except_episode_seconds
from omi_hil_rl.hil.networks import SAC
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.async_training import remaining_episode_budget
from omi_hil_rl.training.eef_bc_grid import GridProfile
from test_cached_replay import contract, episode, buffer


class TinyMultimodalEncoder(nn.Module):
    def __init__(self, recipe):
        super().__init__()
        self.model=nn.Module()
        self.model.backbone=nn.Linear(3,4)
        self.model.touch=nn.Linear(10,4)
        self.model.head=nn.Linear(8,128)
    def forward(self, obs):
        visual=self.model.backbone(obs['rgb'].float().mean((1,3,4))/255.)
        touch=self.model.touch(obs['tactile'].float().mean((1,3,4)))
        return self.model.head(torch.cat((visual,touch),-1))


@pytest.mark.parametrize('tactile,fusion',[(True,False),(False,True),(True,True)])
def test_selective_weights_change_only_after_warmup_and_resume(monkeypatch,tactile,fusion):
    import omi_hil_rl.hil.networks as module
    monkeypatch.setattr(module,'Encoder',TinyMultimodalEncoder)
    torch.set_num_threads(1);torch.manual_seed(7)
    cfg=HILConfig()
    recipe=dict(encoder='current9stack',base_contract=GridProfile(cfg.wrist_camera).CONTRACT)
    bc=SAC(recipe,cfg.replay_contract())
    agent=SAC(recipe,cfg.replay_contract(),freeze_encoder=True,critic_warmup_updates=2,bc_weight=10.,
              train_tactile_encoder=tactile,train_fusion_layer=fusion,encoder_learning_rate=1e-5)
    agent.initialize_bc(bc.checkpoint())
    initial=deepcopy(agent.actor.state_dict())
    obs={k:torch.as_tensor(v)[None] for k,v in FakeTransport(cfg)._observation().items()}
    obs['tactile'].fill_(.2)
    b=NS(observations=obs,next_observations=obs,actions=torch.full((1,6),.2),
         rewards=torch.ones(1,1),dones=torch.zeros(1,1))
    for _ in range(2):
        result=agent.update(b,b)
        assert not result['tactile_encoder_trainable'] and not result['fusion_layer_trainable']
        assert all(torch.equal(v,initial[k]) for k,v in agent.actor.state_dict().items())
    restored=SAC.restore(deepcopy(agent.checkpoint()))
    assert restored.train_tactile_encoder==tactile and restored.train_fusion_layer==fusion
    assert [g['lr'] for g in restored.critic_optimizer.param_groups]==[3e-4,1e-5]
    restored.update(b,b);result=restored.update(b,b)
    for prefix,expected in [('encoder.model.touch.',tactile),('encoder.model.head.',fusion),
                            ('encoder.model.backbone.',False)]:
        assert any(not torch.equal(v,initial[k]) for k,v in restored.actor.state_dict().items() if k.startswith(prefix))==expected
    assert result['tactile_encoder_trainable']==tactile and result['fusion_layer_trainable']==fusion
    assert all(torch.equal(v,initial[k]) for k,v in restored.bc_reference.state_dict().items())
    resumed=SAC.restore(deepcopy(restored.checkpoint()))
    assert resumed.critic_optimizer.state_dict()['state']
    resumed.update(b,b)


def test_legacy_checkpoint_without_selective_flags_stays_frozen():
    agent=SAC({'encoder':'synthetic-test'},HILConfig().replay_contract(),freeze_encoder=True)
    state=agent.checkpoint()
    for key in ('train_tactile_encoder','train_fusion_layer','encoder_learning_rate'):
        state['hyperparameters'].pop(key)
    restored=SAC.restore(state)
    assert not restored.train_tactile_encoder and not restored.train_fusion_layer
    assert not any(p.requires_grad for p in restored.actor.encoder.parameters())


def test_horizon_only_transfer_never_relaxes_action_or_observation_contract():
    c=HILConfig(episode_seconds=20)
    target=replace(c,episode_seconds=30).replay_contract()
    assert same_contract_except_episode_seconds(c.replay_contract(),target)
    assert not same_contract_except_episode_seconds(c.replay_contract(),replace(c,episode_seconds=30,translation_step_m=.1).replay_contract())
    target['config']['episode_seconds']=20
    assert not same_contract_except_episode_seconds(c.replay_contract(),target)


def test_cached_seed_changes_only_target_horizon_and_preserves_source_timeout(tmp_path):
    source=contract();source['episode_seconds']=source['config']['episode_seconds']=20.
    target=deepcopy(source);target['episode_seconds']=target['config']['episode_seconds']=30.
    path,_=episode(tmp_path/'data','demo',source,success=False)
    original=path.read_bytes()
    r=buffer(tmp_path/'replay',target)
    try:
        with pytest.raises(ValueError,match='mismatched'):
            r.register_episode(path,seed=True)
        with pytest.raises(ValueError,match='initial seeds'):
            r.register_episode(path,allow_seed_horizon_change=True)
        assert r.register_episode(path,seed=True,allow_seed_horizon_change=True)==1
        r.seal_seed();r.wait_idle()
        row=r.db.execute('SELECT metadata FROM records').fetchone()
        meta=json.loads(row[0])
        assert meta['seed_horizon_transfer']==dict(source_episode_seconds=20.,target_episode_seconds=30.)
        assert meta['truncated'] and not meta['terminated'] and meta['reward']==0
        assert path.read_bytes()==original
        batch=r.sample_human(1)
        assert not batch.dones.any()  # original timeout still bootstraps
    finally:r.close()


def test_persistent_300_cap_counts_original_started_episodes_not_segments(tmp_path):
    session=dict(control_mode='periodic_training_v1',max_total_episodes=300)
    assert remaining_episode_budget(tmp_path,session,300)==300
    for i in range(299):
        p=tmp_path/'periodic_episodes'/str(i);p.mkdir(parents=True)
        (p/'staging.json').write_text('{}');(p/'audit.json').write_text('{}')
    assert remaining_episode_budget(tmp_path,session,300)==1
    p=tmp_path/'periodic_episodes'/'last';p.mkdir();(p/'staging.json').write_text('{}')
    assert remaining_episode_budget(tmp_path,session,300)==0
    assert remaining_episode_budget(tmp_path,{},300)==300


@pytest.mark.skipif(not torch.cuda.is_available(),reason='CUDA required')
@pytest.mark.parametrize('fusion',[False,True])
def test_actual_bc_cuda_selective_update_and_checkpoint_restore(fusion):
    from omi_hil_rl.hil.exchange import read_episode
    path=Path('local/rl_training/spacepilot_bc_20261017_213359_2000_4000')
    if not (path/'actor.pt').exists():pytest.skip('local BC6148 fixture absent')
    torch.set_num_threads(2)
    state=torch.load(path/'actor.pt',map_location='cpu',weights_only=True)
    agent=SAC(state['recipe'],state['contract'],device='cuda',freeze_encoder=True,critic_warmup_updates=2,
              train_tactile_encoder=True,train_fusion_layer=fusion,encoder_learning_rate=1e-5,
              bc_weight=10.,actor_learning_rate=1e-5,image_augmentation=False)
    agent.initialize_bc(state)
    entry=json.loads((path/'dataset.json').read_text())['episodes'][0]
    record=next(read_episode(entry['path'],entry['manifest']))
    b=NS(observations={k:torch.as_tensor(v)[None] for k,v in record['observation'].items()},
         next_observations={k:torch.as_tensor(v)[None] for k,v in record['next_observation'].items()},
         actions=torch.as_tensor(record['executed_action'])[None],rewards=torch.ones(1,1),dones=torch.zeros(1,1))
    for _ in range(2):
        result=agent.update(b,b)
        assert result['bc_reference_max_abs']==0
    restored=SAC.restore(agent.checkpoint(),device='cuda')
    restored.update(b,b);result=restored.update(b,b)
    now=restored.actor.state_dict()
    for prefix,changed in (('encoder.model.touch.',True),('encoder.model.head.',fusion)):
        assert any(not torch.equal(v.cpu(),state['actor'][k]) for k,v in now.items() if k.startswith(prefix))==changed
    assert all(torch.equal(v.cpu(),state['actor'][k]) for k,v in now.items()
               if k.startswith('encoder.') and not k.startswith(('encoder.model.touch.','encoder.model.head.')))
    assert result['tactile_encoder_trainable'] and result['fusion_layer_trainable']==fusion
    print('CUDA_SELECTIVE_ENCODER_OK',result['update'],result['bc_loss'])
