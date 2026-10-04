"""PyTorch inference port of the SERL ImageNet ResNet-10 (GroupNorm).

Architecture reference: rail-berkeley/serl, vision/resnet_v1.py (Apache-2.0).
Preserves Flax SAME padding, including its asymmetric stride-2 padding.
Runtime needs only PyTorch; conversion accepts plain numeric NPZ arrays.
"""
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def same_pad(x, kernel, stride, value=0.):
    h, w = x.shape[-2:]
    ph = max(((h + stride - 1) // stride - 1) * stride + kernel - h, 0)
    pw = max(((w + stride - 1) // stride - 1) * stride + kernel - w, 0)
    return F.pad(x, (pw // 2, pw - pw // 2, ph // 2, ph - ph // 2), value=value)


class Block(nn.Module):
    def __init__(self, incoming, outgoing, stride):
        super().__init__()
        self.stride = stride
        self.conv0 = nn.Conv2d(incoming, outgoing, 3, stride=stride, bias=False)
        self.norm0 = nn.GroupNorm(4, outgoing, eps=1e-5)
        self.conv1 = nn.Conv2d(outgoing, outgoing, 3, padding=1, bias=False)
        self.norm1 = nn.GroupNorm(4, outgoing, eps=1e-5)
        if incoming != outgoing or stride != 1:
            self.proj = nn.Conv2d(incoming, outgoing, 1, stride=stride, bias=False)
            self.proj_norm = nn.GroupNorm(4, outgoing, eps=1e-5)
        else:
            self.proj = self.proj_norm = nn.Identity()

    def forward(self, x):
        y = F.relu(self.norm0(self.conv0(same_pad(x, 3, self.stride))))
        y = self.norm1(self.conv1(y))
        return F.relu(y + self.proj_norm(self.proj(x)))


class SerlResNet10(nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = nn.Conv2d(3, 64, 7, stride=2, padding=3, bias=False)
        self.stem_norm = nn.GroupNorm(4, 64, eps=1e-5)
        self.blocks = nn.ModuleList([Block(64, 64, 1), Block(64, 128, 2),
                                     Block(128, 256, 2), Block(256, 512, 2)])
        self.register_buffer('mean', torch.tensor([.485, .456, .406]).view(1, 3, 1, 1))
        self.register_buffer('std', torch.tensor([.229, .224, .225]).view(1, 3, 1, 1))

    def forward(self, rgb):
        if rgb.ndim != 4 or rgb.shape[1:] != (3, 128, 128):
            raise ValueError('Expected RGB float32 [N,3,128,128] in [0,1]')
        x = F.relu(self.stem_norm(self.stem((rgb - self.mean) / self.std)))
        x = F.max_pool2d(same_pad(x, 3, 2, float('-inf')), 3, stride=2)
        for block in self.blocks:
            x = block(x)
        return x


def convert_npz(source, output):
    """Convert audited Flax HWIO arrays, with strict keys/shapes, to weights-only PT."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    model = SerlResNet10()
    state = model.state_dict()
    mapping = {'stem.weight': 'conv_init/kernel',
               'stem_norm.weight': 'norm_init/scale', 'stem_norm.bias': 'norm_init/bias'}
    for i in range(4):
        for j in range(2):
            mapping[f'blocks.{i}.conv{j}.weight'] = f'ResNetBlock_{i}/Conv_{j}/kernel'
            for dest, src in [('weight', 'scale'), ('bias', 'bias')]:
                mapping[f'blocks.{i}.norm{j}.{dest}'] = f'ResNetBlock_{i}/MyGroupNorm_{j}/{src}'
        if i:
            mapping[f'blocks.{i}.proj.weight'] = f'ResNetBlock_{i}/conv_proj/kernel'
            for dest, src in [('weight', 'scale'), ('bias', 'bias')]:
                mapping[f'blocks.{i}.proj_norm.{dest}'] = f'ResNetBlock_{i}/norm_proj/{src}'
    with np.load(source, allow_pickle=False) as arrays:
        expected = set(mapping.values())
        # The released checkpoint also contains the ImageNet classifier, unused here.
        extras = set(arrays.files) - expected
        if extras - {'output_head/kernel', 'output_head/bias'} or expected - set(arrays.files):
            raise ValueError(f'Unexpected checkpoint keys: {extras}, missing {expected-set(arrays.files)}')
        for dest, src in mapping.items():
            a = arrays[src]
            if a.ndim == 4:
                a = a.transpose(3, 2, 0, 1)
            if a.shape != tuple(state[dest].shape) or not np.isfinite(a).all():
                raise ValueError(f'Invalid pretrained array: {src}')
            state[dest] = torch.from_numpy(a.copy()).float()
    model.load_state_dict(state, strict=True)
    torch.save(state, output)
    return model
