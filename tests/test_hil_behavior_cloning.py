import numpy as np
import torch

from omi_hil_rl.hil.behavior_cloning import bc_update, metrics
from omi_hil_rl.hil.networks import Actor


def test_bc_learns_human_target_without_critic():
    torch.set_num_threads(1)
    torch.manual_seed(7)
    actor = Actor({'encoder': 'synthetic-test'}).eval()
    obs = {'state': torch.zeros(8, 10, 14), 'tactile': torch.zeros(8, 10, 10, 16, 24)}
    labels = torch.zeros(8, 6)
    labels[:, 0] = .4
    optimizer = torch.optim.Adam(actor.parameters(), lr=1e-4)
    before = float((actor.sample(obs, True)[0]-labels).square().mean().detach())
    for _ in range(100):
        bc_update(actor, optimizer, obs, labels)
    after = float((actor.sample(obs, True)[0]-labels).square().mean().detach())
    assert after < before*.05


def test_metrics_rotation_and_physical_units():
    target = np.zeros((2, 6))
    target[:, 0] = 1
    prediction = target.copy()
    prediction[:, 3] = .2
    result = metrics(prediction, target, np.array([.001]*3+[np.pi/180]*3))
    assert result['moving_dx_sign_accuracy'] == 1
    assert result['zero_rotation_false_motion_fraction'] == 1
    assert np.isclose(result['physical_mae_mm_deg'][3], .2)


def test_bc_actor_roundtrip(tmp_path):
    from omi_hil_rl.hil.config import HILConfig
    from omi_hil_rl.hil.exchange import atomic_torch
    from omi_hil_rl.hil.networks import VERSION, load_actor
    recipe = {'encoder': 'synthetic-test'}
    contract = HILConfig().replay_contract()
    actor = Actor(recipe).eval()
    obs = {'state': torch.zeros(1, 10, 14), 'tactile': torch.zeros(1, 10, 10, 16, 24)}
    atomic_torch(tmp_path/'actor.pt', dict(version=VERSION, recipe=recipe, contract=contract,
        updates=59, actor=actor.state_dict(), training_method='behavior_cloning'))
    loaded, version, _ = load_actor(tmp_path/'actor.pt', contract)
    assert version == 59
    assert torch.equal(actor.sample(obs, True)[0], loaded.sample(obs, True)[0])
