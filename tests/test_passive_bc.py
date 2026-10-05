"""Recorded-command conversion, split integrity and a real wrench input branch."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.training.passive_bc import inverse_wire, contract_for, make_plan, PassiveDataset, VERSION, PERIOD
from omi_hil_rl.training.demo_bc import statistics, dataset_for_plan
from omi_hil_rl.hil.demo import save_npz
from omi_hil_rl.hil.networks import Actor
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.transition_replay import _spaces


def provenance():
    return dict(rate_hz=10, effective_translation_mm_s=5., effective_rotation_deg_s=5.,
                output_convention='sdk-x-forward-z-left')


@pytest.mark.parametrize('convention', ['sdk-base-aligned', 'sdk-x-forward-z-left'])
def test_full_rotation_and_frame_inverse_roundtrip(convention):
    random = np.random.default_rng(12)
    for _ in range(30):
        action = random.uniform(-1, 1, 6) * np.array([.0005] * 3 + [.008] * 3)
        wire = output_action(action, convention)
        np.testing.assert_allclose(inverse_wire(wire, convention), action, atol=1e-12)
    wire = [0., 0., .5, 0., 0., -.5]
    result = inverse_wire(wire, 'sdk-x-forward-z-left')
    np.testing.assert_allclose(result, [0., .0005, 0., 0., -np.radians(.5), 0.], atol=1e-12)


def observation(contract):
    obs = {k: np.zeros(s['shape'], s['dtype']) for k, s in contract['observations'].items()}
    obs['history_mask'][:] = 1
    obs['camera_mask'][:] = 1
    obs['wrench_mask'][:] = 1
    obs['state'][:, -1] = 1
    return obs


def fixture_dataset(root):
    contract = contract_for(provenance())
    for name in ('bag_a', 'bag_b'):
        directory = root / 'episodes' / name
        directory.mkdir(parents=True)
        obs = observation(contract)
        action = np.array([.5, 0., 0., 0., 0., 0.], np.float32)
        physical = action * contract['physical_action_scale']
        wire = output_action(physical, contract['config']['sdk_convention'])
        reference = 10**12
        stamps = np.broadcast_to((reference - np.arange(9, -1, -1) * PERIOD)[:, None], (10, 2))
        metadata = dict(observation_time_ns=reference, command_receive_ns=reference + 99_000_000,
                        wire_action=wire)
        arrays = {'observation__' + k: v for k, v in obs.items()}
        arrays.update(action=action, metadata=np.asarray(json.dumps(metadata)),
                      recorded_wire_action=np.asarray(wire), wrench_receive_ns=stamps)
        save_npz(directory / '000000.npz', arrays)
        (directory / 'dataset.json').write_text(json.dumps(dict(version=VERSION, episode=name, count=1, contract=contract)))
    return make_plan(root, 'bag_b')


def test_distinct_contract_and_whole_bag_split(tmp_path):
    plan = fixture_dataset(tmp_path)
    assert plan['training'][0]['episode'] == 'bag_a'
    assert plan['validation'][0]['episode'] == 'bag_b'
    assert len(dataset_for_plan(plan, 'training')) == 1
    with pytest.raises(ValueError, match='accepted_command'):
        _spaces(plan['contract'])
    changed = copy.deepcopy(plan)
    changed['validation'] = changed['training']
    with pytest.raises(ValueError, match='leakage'):
        PassiveDataset(changed, 'training')


def test_dataset_hash_and_future_wrench_are_rejected(tmp_path):
    plan = fixture_dataset(tmp_path)
    ep = plan['training'][0]
    path = Path(ep['path']) / '000000.npz'
    with np.load(path) as archive:
        values = {k: archive[k].copy() for k in archive.files}
    values['wrench_receive_ns'] += 1
    # Test artifact rewrite is intentional; bypass hash to exercise time validation too.
    with path.open('wb') as stream:
        np.savez_compressed(stream, **values)
    with pytest.raises(ValueError, match='hash mismatch'):
        PassiveDataset(plan, 'training')
    ep['samples_sha256'] = [sha256(path)]
    with pytest.raises(ValueError, match='noncausal'):
        PassiveDataset(plan, 'training')


def test_training_only_wrench_statistics(tmp_path):
    plan = fixture_dataset(tmp_path)
    data = PassiveDataset(plan, 'training')
    norm, mean = statistics(data)
    assert norm['wrench_valid_counts'] == [10, 10]
    assert np.asarray(norm['wrench_mean']).shape == (2, 6)
    np.testing.assert_allclose(norm['wrench_std'], .001)
    assert mean[0] == .5


def test_wrench_changes_prediction_receives_gradient_and_mask_blocks_it():
    torch.set_num_threads(2)
    torch.manual_seed(7)
    contract = contract_for(provenance())
    norm = dict(tactile_mean=np.zeros(10).tolist(), tactile_std=np.ones(10).tolist(),
                state_mean=np.zeros(14).tolist(), state_std=np.ones(14).tolist(),
                wrench_mean=np.zeros((2, 6)).tolist(), wrench_std=np.ones((2, 6)).tolist())
    actor = Actor(dict(encoder='current9stack', base_contract=GridProfile('required').CONTRACT,
                       normalization=norm, wrench_history=True)).eval()
    obs = {k: torch.as_tensor(v)[None] for k, v in observation(contract).items()}
    first = actor.sample(obs, deterministic=True)[0]
    obs['wrench'] = torch.ones_like(obs['wrench'], requires_grad=True)
    second = actor.sample(obs, deterministic=True)[0]
    assert not torch.allclose(first, second)
    second.square().sum().backward()
    assert obs['wrench'].grad.abs().sum() > 0
    assert actor.encoder.wrench_encoder[0].weight.grad.abs().sum() > 0
    assert all(p.grad is None for p in actor.encoder.model.backbone.parameters())
    obs['wrench_mask'] = torch.zeros_like(obs['wrench_mask'])
    with torch.no_grad():
        first = actor.sample(obs, deterministic=True)[0]
        obs['wrench'] *= 10000
        second = actor.sample(obs, deterministic=True)[0]
    torch.testing.assert_close(first, second)
