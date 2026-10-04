"""Frozen backbone, cache, masking and checkpoint boundaries for ResNet BC."""
import pytest
import torch

from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.eef_bc_resnet import ResNetHistoryPolicy, load_resnet_history, VERSION
from omi_hil_rl.training.serl_resnet10 import same_pad


@pytest.fixture
def model():
    torch.set_num_threads(2)
    torch.manual_seed(7)
    return ResNetHistoryPolicy(GridProfile().CONTRACT).eval()


def sample():
    return (torch.rand(3, 3, 128, 128), torch.randn(3, 10, 16, 24),
            torch.randn(3, 14), torch.rand(3, 3, 128, 128),
            torch.tensor([[1., 1.], [1., 0.], [1., 1.]]))


def test_flax_same_padding_is_asymmetric_for_even_stride_two():
    x = torch.ones(1, 1, 4, 4)
    p = same_pad(x, 3, 2)
    assert p.shape[-2:] == (5, 5)
    assert torch.all(p[..., :4, :4] == 1)
    assert torch.all(p[..., -1, :] == 0)
    assert torch.all(p[..., :, -1] == 0)


def test_raw_cached_missing_camera_and_checkpoint(model, tmp_path):
    x = sample()
    index = torch.full((2, 10), -1)
    index[0, -2:] = torch.tensor([0, 1]); index[1, -3:] = torch.tensor([0, 1, 2])
    cached = model.cache_inputs(x)
    with torch.no_grad():
        expected = model(x, index)
        torch.testing.assert_close(expected, model.forward_cached(cached, index))
        changed = list(cached); changed[3] = changed[3].clone(); changed[3][1] = 10000
        torch.testing.assert_close(expected, model.forward_cached(tuple(changed), index), rtol=0, atol=0)
    checkpoint = tmp_path/'model.pt'
    torch.save(dict(config=dict(version=VERSION, history_slots=10, period_ns=100_000_000,
                                base_contract=GridProfile().CONTRACT, normalization={}),
                    state_dict=model.state_dict()), checkpoint)
    loaded, _, _ = load_resnet_history(checkpoint)
    with torch.no_grad():
        torch.testing.assert_close(expected, loaded(x, index), rtol=0, atol=0)


def test_frozen_backbone_and_projection_gradients(model):
    x = sample(); cached = model.cache_inputs(x)
    index = torch.full((1, 10), -1); index[0, -3:] = torch.arange(3)
    # Disable random camera dropout for this gradient coverage assertion.
    model.encoder.contract = dict(model.encoder.contract, wrist_training_dropout=0.)
    model.train()
    assert not model.backbone.training
    before = {k: p.clone() for k, p in model.backbone.state_dict().items()}
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=.001)
    model.forward_cached(cached, index).square().sum().backward()
    assert all(p.grad is None for p in model.backbone.parameters())
    for layer in (model.encoder.rgb[0], model.encoder.wrist[0], model.encoder.touch[0], model.gru):
        assert any(p.grad is not None and torch.count_nonzero(p.grad) for p in layer.parameters())
    optimizer.step()
    assert all(torch.equal(before[k], v) for k, v in model.backbone.state_dict().items())


def test_missing_history_no_influence(model):
    features = torch.randn(1, 10, 128, requires_grad=True)
    mask = torch.ones(1, 10, dtype=torch.bool); mask[:, 2] = False
    output = model.from_features(features, mask)
    modified = features.detach().clone(); modified[:, 2] = 10000
    torch.testing.assert_close(output, model.from_features(modified, mask), rtol=0, atol=0)
    output.sum().backward()
    assert torch.count_nonzero(features.grad[:, 2]) == 0
    assert torch.count_nonzero(features.grad[:, 0]) > 0


def test_reject_other_contract(model):
    contract = dict(GridProfile().CONTRACT)
    contract['version'] = 'invalid'
    with pytest.raises(ValueError):
        ResNetHistoryPolicy(contract)
