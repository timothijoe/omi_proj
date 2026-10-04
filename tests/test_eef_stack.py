import pytest
import torch
from torch import nn

from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.eef_bc_stack import CurrentStackPolicy, load_stack_policy, VERSION


@pytest.fixture
def model():
    torch.set_num_threads(2)
    torch.manual_seed(7)
    m = CurrentStackPolicy(GridProfile().CONTRACT)
    m.initialize_pretrained(m.backbone.state_dict())
    return m.eval()


def sample():
    return (torch.rand(1, 10, 3, 128, 128), torch.randn(1, 10, 10, 16, 24),
            torch.randn(1, 10, 14), torch.rand(1, 10, 3, 128, 128), torch.ones(1, 10, 2))


def test_repeated_identical_history_matches_original_pretrained_stem(model):
    image = torch.rand(1, 3, 128, 128)
    with torch.no_grad():
        expected = model.backbone(image)
        actual = model.history_features(image[:, None].repeat(1, 9, 1, 1, 1), torch.ones(1, 9, dtype=torch.bool))
    torch.testing.assert_close(actual, expected, atol=2e-5, rtol=2e-5)


def test_missing_slots_and_absent_wrist_have_no_effect(model):
    x = sample(); mask = torch.ones(1, 10, dtype=torch.bool); mask[:, 2] = False
    x[4][:, :, 1] = 0
    changed = [v.clone() for v in x]
    for v in changed[:4]:
        v[:, 2] = 1000
    changed[3][:] = 2000
    with torch.no_grad():
        expected = model.forward_windows(x, mask)
        torch.testing.assert_close(model.forward_windows(tuple(changed), mask), expected, rtol=0, atol=0)
    mask[:, -1] = False
    with pytest.raises(ValueError, match='Current observation'):
        model.forward_windows(x, mask)


def test_trainable_stem_receives_gradient_through_frozen_suffix(model):
    model.contract = dict(model.contract, wrist_training_dropout=0.)
    x = sample(); mask = torch.ones(1, 10, dtype=torch.bool)
    frozen = {k: v.clone() for k, v in model.backbone.state_dict().items()}
    stem = model.history_stem.weight.detach().clone()
    model.train()
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=1e-4)
    model.forward_windows(x, mask).square().sum().backward()
    assert torch.count_nonzero(model.history_stem.weight.grad) > 0
    assert not torch.equal(model.history_stem.weight.grad[:, :3], model.history_stem.weight.grad[:, -3:])
    assert all(p.grad is None for p in model.backbone.parameters())
    assert torch.count_nonzero(model.touch[0].weight.grad) > 0
    for proj in (*model.current_projection, *model.history_projection):
        assert torch.count_nonzero(proj[0].weight.grad) > 0
    optimizer.step()
    assert not torch.equal(stem, model.history_stem.weight)
    assert all(torch.equal(v, frozen[k]) for k, v in model.backbone.state_dict().items())
    assert not any(isinstance(m, (nn.GRU, nn.GRUCell)) for m in model.modules())


def test_cache_reload_and_version_boundary(model, tmp_path):
    window = sample(); pool = tuple(v[0] for v in window)
    index = torch.arange(10)[None]
    with torch.no_grad():
        maps = model.cache_current(pool)
        expected = model(pool, index)
        torch.testing.assert_close(expected, model(pool, index, maps), atol=1e-6, rtol=1e-5)
    cfg = dict(version=VERSION, base_contract=GridProfile().CONTRACT, normalization={}, history_slots=10, period_ns=100_000_000)
    p = tmp_path/'model.pt'
    torch.save(dict(config=cfg, state_dict=model.state_dict()), p)
    loaded, _, _ = load_stack_policy(p)
    with torch.no_grad():
        torch.testing.assert_close(expected, loaded(pool, index), atol=0, rtol=0)
    cfg['version'] = 'eef-history-v1'
    torch.save(dict(config=cfg, state_dict=model.state_dict()), p)
    with pytest.raises(ValueError, match='Incompatible'):
        load_stack_policy(p)


def test_no_joint_version_ignores_joints_but_uses_pose(tmp_path):
    from omi_hil_rl.training.eef_bc_stack import NO_JOINT_VERSION
    torch.set_num_threads(2)
    torch.manual_seed(7)
    model = CurrentStackPolicy(GridProfile().CONTRACT, joint_mode='off').eval()
    x = sample(); mask = torch.ones(1, 10, dtype=torch.bool)
    x[2].requires_grad_()
    expected = model.forward_windows(x, mask)
    expected.sum().backward()
    assert torch.count_nonzero(x[2].grad[..., :7]) == 0
    assert torch.count_nonzero(x[2].grad[..., 7:]) > 0
    changed = [v.detach().clone() for v in x]
    changed[2][..., :7] = float('nan')
    with torch.no_grad():
        torch.testing.assert_close(model.forward_windows(tuple(changed), mask), expected, atol=0, rtol=0)
    cfg = dict(version=NO_JOINT_VERSION, joint_mode='off', joint_enabled=0, joint_mask=0,
               base_contract=GridProfile().CONTRACT, normalization={}, history_slots=10, period_ns=100_000_000)
    p = tmp_path/'no_joints.pt'
    torch.save(dict(config=cfg, state_dict=model.state_dict()), p)
    loaded, _, _ = load_stack_policy(p)
    with torch.no_grad():
        torch.testing.assert_close(loaded.forward_windows(x, mask), expected, atol=0, rtol=0)
    cfg['joint_enabled'] = 1
    torch.save(dict(config=cfg, state_dict=model.state_dict()), p)
    with pytest.raises(ValueError, match='disabled'):
        load_stack_policy(p)


def test_fixed_tactile_pool_matches_adaptive_values_and_gradients():
    a = torch.randn(3, 16, 8, 12, requires_grad=True)
    b = a.detach().clone().requires_grad_()
    fixed = nn.AvgPool2d(4)(a)
    adaptive = nn.AdaptiveAvgPool2d((2, 3))(b)
    torch.testing.assert_close(fixed, adaptive, atol=0, rtol=0)
    fixed.square().sum().backward(); adaptive.square().sum().backward()
    torch.testing.assert_close(a.grad, b.grad, atol=0, rtol=0)
