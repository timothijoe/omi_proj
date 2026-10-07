from copy import deepcopy
import os
import signal
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.networks import SAC, augment_images
from omi_hil_rl.hil.shutdown import graceful_stop


@pytest.fixture(autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def test_shared_encoder_has_one_optimizer_owner_and_independent_target():
    agent = SAC(dict(encoder='synthetic-test'), HILConfig().replay_contract())
    assert agent.actor.encoder is agent.critic.encoder
    assert agent.target.encoder is not agent.critic.encoder
    actor_ids = {id(p) for g in agent.actor_optimizer.param_groups for p in g['params']}
    critic_ids = {id(p) for g in agent.critic_optimizer.param_groups for p in g['params']}
    assert actor_ids.isdisjoint(critic_ids)
    assert {id(p) for p in agent.actor.encoder.parameters()} <= critic_ids
    obs = agent.observation(FakeTransport()._observation(), single=True)
    action, _ = agent.actor.sample(obs, detach_encoder=True)
    action.sum().backward()
    assert all(p.grad is None for p in agent.actor.encoder.parameters())
    assert any(p.grad is not None for p in agent.actor.head.parameters())
    restored = SAC.restore(deepcopy(agent.checkpoint()))
    assert restored.actor.encoder is restored.critic.encoder
    bad = deepcopy(agent.checkpoint())
    key = next(k for k in bad['actor'] if k.startswith('encoder.'))
    bad['actor'][key] = bad['actor'][key] + 1
    with pytest.raises(ValueError, match='copies disagree'):
        SAC.restore(bad)
    bad['version'] = 'omi-hil-sac-no-gripper-v1'
    with pytest.raises(ValueError, match='new v2 run'):
        SAC.restore(bad)


def test_official_head_dimensions_and_distribution_bounds():
    agent = SAC(dict(encoder='synthetic-test'), HILConfig().replay_contract())
    assert [(l.in_features, l.out_features) for l in agent.actor.head if isinstance(l, torch.nn.Linear)] == [(128,256),(256,256),(256,12)]
    for q in agent.critic.heads:
        assert [(l.in_features,l.out_features) for l in q if isinstance(l,torch.nn.Linear)] == [(134,256),(256,256),(256,1)]
    assert torch.nn.functional.softplus(agent.temperature_raw).item() == pytest.approx(.01)
    obs = agent.observation(FakeTransport()._observation(), single=True)
    with torch.no_grad():
        agent.actor.head[-1].weight.zero_()
        agent.actor.head[-1].bias[6:] = 1000
        action, log_prob = agent.actor.sample(obs)
    assert torch.isfinite(action).all() and torch.isfinite(log_prob).all()


def test_augmentation_preserves_temporal_alignment_dtype_and_source():
    torch.manual_seed(9)
    frame = torch.arange(64, dtype=torch.uint8).reshape(1,1,1,8,8)
    image = frame.expand(4,10,3,8,8).clone()
    obs = dict(rgb=image, wrist_rgb=image.clone(), state=torch.zeros(4,10,14))
    result = augment_images(obs)
    assert torch.equal(image, frame.expand_as(image))
    assert result['state'] is obs['state']
    for key in ('rgb','wrist_rgb'):
        assert result[key].dtype == image.dtype and result[key].shape == image.shape
        assert torch.equal(result[key][:,0], result[key][:,9])
        assert not torch.equal(result[key], image)


def test_stop_signals_are_deferred_and_handlers_restored():
    original = signal.getsignal(signal.SIGINT)
    with graceful_stop() as stopped:
        assert not stopped()
        os.kill(os.getpid(), signal.SIGINT)
        assert stopped()
        os.kill(os.getpid(), signal.SIGTERM)
        assert stopped()
    assert signal.getsignal(signal.SIGINT) == original


def test_recorded_observation_updates_reload_and_resume():
    from types import SimpleNamespace
    from omi_hil_rl.hil.exchange import read_episode
    root = Path(__file__).resolve().parents[1]
    run = root/'local/rl_training/offline_20261006_v1'
    if not (run/'dataset.json').exists():
        pytest.skip('local recorded dataset unavailable')
    index = json.loads((run/'dataset.json').read_text())['episodes']
    ep = next(ep for ep in index if ep['split'] == 'training')
    record = next(read_episode(ep['path'], ep['manifest']))
    config = HILConfig(**json.loads((run/'config.json').read_text()))
    recipe = json.loads((run/'recipe.json').read_text())
    agent = SAC(recipe, config.replay_contract(), pretrained=torch.load(
        root/'local/pretrained/serl_resnet10/backbone.pt', weights_only=True))
    batch = SimpleNamespace(observations=agent.observation(record['observation'], single=True),
        next_observations=agent.observation(record['next_observation'], single=True),
        actions=torch.as_tensor(record['executed_action'])[None], rewards=torch.tensor([[record['reward']]]),
        dones=torch.tensor([[float(record['terminated'])]]))
    for _ in range(2):
        assert all(np.isfinite(v) for v in agent.update(batch).values())
    saved = deepcopy(agent.checkpoint())
    expected = agent.act(record['observation'], True)
    expected_update = agent.update(batch)
    expected_after = agent.act(record['observation'], True)
    restored = SAC.restore(saved)
    np.testing.assert_array_equal(restored.act(record['observation'], True), expected)
    actual_update = restored.update(batch)
    assert actual_update == expected_update
    np.testing.assert_array_equal(restored.act(record['observation'], True), expected_after)
