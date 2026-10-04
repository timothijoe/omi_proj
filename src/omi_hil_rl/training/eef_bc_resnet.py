"""Offline frozen SERL ResNet-10 + existing causal GRU experiment.

Separate checkpoint version and entry point; no change to existing online policies.
Cache only the frozen backbone maps. Train both spatial projections, tactile CNN,
fusion, GRU and action head from scratch using the original BC objective.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn

from .eef_bc_data import sha256
from .eef_bc_policy import inputs, normalization
from .eef_bc_history import HistoryPolicy, load_history, scores, SLOTS, PERIOD_NS
from .serl_resnet10 import SerlResNet10

VERSION = 'eef-history-resnet10-frozen-v1'


def projection():
    # Preserve all 4x4 locations; lightweight alternative to SERL's 1.1M/view head.
    return nn.Sequential(nn.Conv2d(512, 16, 1), nn.Flatten(), nn.LayerNorm(256), nn.Tanh())


class ResNetHistoryPolicy(HistoryPolicy):
    def __init__(self, contract):
        super().__init__(contract)
        if contract['version'] != 'bag-eef-bc-v3-grid-receive':
            raise ValueError('This experiment requires the original v3 data contract')
        self.backbone = SerlResNet10().requires_grad_(False).eval()
        self.encoder.rgb = projection()
        self.encoder.wrist = projection()

    def train(self, mode=True):
        super().train(mode)
        self.backbone.eval()
        return self

    def cache_inputs(self, x, batch_size=32):
        maps = []
        # Missing wrist frames stay exactly zero; available frames share one backbone.
        for image, valid in [(x[0], x[4][:, 0].bool()), (x[3], x[4][:, 1].bool())]:
            result = image.new_zeros((len(image), 512, 4, 4))
            ids = torch.nonzero(valid, as_tuple=True)[0]
            with torch.no_grad():
                for ix in ids.split(batch_size):
                    result[ix] = self.backbone(image[ix])
            maps.append(result)
        return maps[0], x[1], x[2], maps[1], x[4]

    def encode_cached(self, x):
        return self.project(self.encoder(*x))

    def encode(self, x):
        return self.encode_cached(self.cache_inputs(x))

    def forward_cached(self, x, indices):
        mask = indices >= 0
        unique, inverse = torch.unique(indices[mask], sorted=True, return_inverse=True)
        encoded = self.encode_cached(tuple(v[unique] for v in x))
        features = encoded.new_zeros((*indices.shape, 128))
        features[mask] = encoded[inverse]
        return self.from_features(features, mask)


def predict_cached(model, x, index, norm):
    model.eval()
    with torch.no_grad():
        encoded = torch.cat([model.encode_cached(tuple(v[i:i+64] for v in x))
                             for i in range(0, len(x[0]), 64)])
        predictions = []
        for ix in index.split(128):
            mask = ix >= 0
            features = encoded[ix.clamp_min(0)] * mask[:, :, None]
            predictions.append(model.from_features(features, mask))
    return (torch.cat(predictions).numpy() * np.asarray(norm['delta_std'], np.float32)
            + np.asarray(norm['delta_mean'], np.float32))


def load_resnet_history(path):
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    config = checkpoint['config']
    if (config['version'] != VERSION or config['history_slots'] != SLOTS
            or config['period_ns'] != PERIOD_NS):
        raise ValueError('Incompatible ResNet history checkpoint')
    model = ResNetHistoryPolicy(config['base_contract'])
    model.load_state_dict(checkpoint['state_dict'], strict=True)
    return model.eval(), config['normalization'], checkpoint


def run(plan_path, weights, output, steps=2000, seed=7):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if steps < 1:
        raise ValueError('Positive steps required')
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    plan = json.loads(Path(plan_path).read_text())
    data, manifests, idx, ep, ts = load_history(plan['training'])
    val, vm, vi, ve, vt = load_history(plan['validation'])
    contract = manifests[0]['contract']
    if vm[0]['contract'] != contract:
        raise ValueError('Contract mismatch')
    if {m['episode_id'] for m in manifests} & {m['episode_id'] for m in vm}:
        raise ValueError('Episode leakage')
    norm = normalization(data)
    model = ResNetHistoryPolicy(contract)
    model.backbone.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True), strict=True)
    frozen_before = {k: v.clone() for k, v in model.backbone.state_dict().items()}
    output.mkdir(parents=True)
    started = time.monotonic()
    print('Encoding frozen train/validation RGB maps', flush=True)
    x = model.cache_inputs(inputs(data, norm))
    vx = model.cache_inputs(inputs(val, norm))
    cache_seconds = time.monotonic() - started
    # Cache is generated per run from verified input files; no stale disk cache reuse.
    print(f'Frozen encoding finished in {cache_seconds:.2f}s', flush=True)
    target, vtarget = data['action'], val['action']
    y = torch.as_tensor((target - np.asarray(norm['delta_mean'], np.float32))
                        / np.asarray(norm['delta_std'], np.float32))
    index, vindex = torch.as_tensor(idx), torch.as_tensor(vi)
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(trainable, lr=.001)
    config = dict(version=VERSION, base_contract=contract, normalization=norm,
                  history_slots=SLOTS, period_ns=PERIOD_NS, seed=seed, steps=steps,
                  batch_size=32, learning_rate=.001, device='cpu',
                  train_episode_ids=[m['episode_id'] for m in manifests],
                  validation_episode_ids=[m['episode_id'] for m in vm],
                  source_samples_sha256=[m['samples_sha256'] for m in manifests],
                  validation_samples_sha256=[m['samples_sha256'] for m in vm],
                  weights_sha256=sha256(weights),
                  backbone='shared frozen SERL ResNet-10, GN4 eps1e-5, Flax SAME padding',
                  image_normalization='RGB/255 then ImageNet mean/std; no additional resize/crop',
                  visual_projection='independent 512->16 1x1 conv, flatten 4x4, LN256, tanh',
                  missing='skip missing slots; zero state per window; same relative age as original GRU',
                  objective='normalized six-axis action MSE only; no keypoint auxiliary labels',
                  selection='lowest validation normalized MSE; evaluation every100 steps')
    (output/'config.json').write_text(json.dumps(config, indent=2)+'\n')
    (output/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    np.savez_compressed(output/'history_index.npz', train_index=idx, validation_index=vi,
                        train_episode=ep, validation_episode=ve,
                        train_reference_ns=ts, validation_reference_ns=vt)
    history, losses = [], []
    best, best_step = float('inf'), None

    def evaluate(step):
        nonlocal best, best_step
        pred = predict_cached(model, x, index, norm)
        vp = predict_cached(model, vx, vindex, norm)
        row = dict(step=step, train=scores(pred, target, norm), validation=scores(vp, vtarget, norm))
        history.append(row)
        if step and row['validation']['normalized_mse'] < best:
            best, best_step = row['validation']['normalized_mse'], step
            torch.save(dict(config=config, step=step, state_dict=model.state_dict()), output/'best.pt')
        (output/'history.json').write_text(json.dumps(history, indent=2)+'\n')
        print(json.dumps(row), flush=True)
        return pred, vp

    evaluate(0)
    for step in range(1, steps+1):
        model.train()
        batch = torch.randint(len(target), (min(32, len(target)),))
        loss = nn.functional.mse_loss(model.forward_cached(x, index[batch]), y[batch])
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite loss')
        optimizer.zero_grad(); loss.backward()
        nn.utils.clip_grad_norm_(trainable, 5.); optimizer.step()
        if step == 1 or step % 25 == 0:
            losses.append(dict(step=step, normalized_mse=float(loss.detach())))
        if step % 100 == 0 or step == steps:
            pred, vp = evaluate(step)
    torch.save(dict(config=config, step=steps, state_dict=model.state_dict()), output/'last.pt')
    np.savez_compressed(output/'last_predictions.npz', train=pred, validation=vp,
                        train_target=target, validation_target=vtarget,
                        validation_episode=ve, validation_reference_ns=vt)
    if not all(torch.equal(v, frozen_before[k]) for k, v in model.backbone.state_dict().items()):
        raise AssertionError('Frozen backbone changed')
    model, reloaded_norm, checkpoint = load_resnet_history(output/'best.pt')
    if reloaded_norm != norm:
        raise AssertionError('Normalization changed on reload')
    bp = predict_cached(model, vx, vindex, norm)
    best_row = next(h for h in history if h['step'] == best_step)
    np.testing.assert_allclose(scores(bp, vtarget, norm)['normalized_mse'],
                               best_row['validation']['normalized_mse'], rtol=1e-6)
    # Recompute raw image path for several windows, with a fresh backbone pass.
    selected = torch.arange(min(8, len(vi)))
    unique, inverse = torch.unique(vindex[selected][vindex[selected] >= 0], return_inverse=True)
    raw = tuple(v[unique] for v in inputs(val, norm))
    small_index = vindex[selected].clone()
    small_index[small_index >= 0] = inverse
    with torch.no_grad():
        raw_prediction = model(raw, small_index).numpy()
    raw_prediction = raw_prediction*np.asarray(norm['delta_std'], np.float32)+np.asarray(norm['delta_mean'], np.float32)
    np.testing.assert_allclose(raw_prediction, bp[selected], atol=1e-7, rtol=1e-5)
    np.savez_compressed(output/'best_validation_predictions.npz', prediction=bp, target=vtarget,
                        episode=ve, reference_ns=vt)
    mean = target.mean(0)
    only_current = vindex.clone(); only_current[:, :-1] = -1
    report = dict(config=config, samples=len(target), validation_samples=len(vtarget),
                  seconds=time.monotonic()-started, frozen_encoding_seconds=cache_seconds,
                  parameters=sum(p.numel() for p in model.parameters()),
                  trainable_parameters=sum(p.numel() for p in trainable),
                  frozen_parameters=sum(p.numel() for p in model.backbone.parameters()),
                  best_step=best_step, history=history, losses=losses,
                  best_validation=scores(bp, vtarget, norm), last_validation=history[-1]['validation'],
                  zero_baseline=scores(np.zeros_like(vtarget), vtarget, norm),
                  mean_baseline=scores(np.broadcast_to(mean, vtarget.shape), vtarget, norm),
                  best_with_history_masked_at_inference=scores(predict_cached(model, vx, only_current, norm), vtarget, norm),
                  per_episode={vm[i]['episode_id']: scores(bp[ve==i], vtarget[ve==i], norm) for i in range(len(vm))},
                  checks=dict(frozen_backbone_unchanged=True, checkpoint_reload_metrics_match=True,
                              raw_and_cached_predictions_max_abs=float(np.max(np.abs(raw_prediction-bp[selected])))),
                  best_sha256=sha256(output/'best.pt'), last_sha256=sha256(output/'last.pt'),
                  warning='Validation selects checkpoint; no independent test or closed-loop evidence. Offline only.')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=2000)
    p.add_argument('--seed', type=int, default=7)
    a = p.parse_args()
    run(a.plan, a.weights, a.output, a.steps, a.seed)


if __name__ == '__main__':
    main()
