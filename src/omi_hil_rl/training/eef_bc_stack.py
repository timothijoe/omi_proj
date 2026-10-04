"""Offline current RGB + nine channel-stacked past frames, without a GRU."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .eef_bc_data import profile_for, sha256
from .eef_bc_policy import inputs, normalization
from .eef_bc_history import load_history, scores, SLOTS, PERIOD_NS
from .eef_bc_resnet import projection
from .serl_resnet10 import SerlResNet10, same_pad

VERSION = 'eef-current9stack-resnet10-v1'


class CurrentStackPolicy(nn.Module):
    def __init__(self, contract):
        super().__init__()
        self.contract = profile_for(contract).CONTRACT
        if self.contract['version'] != 'bag-eef-bc-v3-grid-receive':
            raise ValueError('Current/stack experiment requires v3 data')
        self.backbone = SerlResNet10().requires_grad_(False).eval()
        self.history_stem = nn.Conv2d(27, 64, 7, stride=2, padding=3, bias=False)
        self.current_projection = nn.ModuleList([projection(), projection()])
        self.history_projection = nn.ModuleList([projection(), projection()])
        self.touch = nn.Sequential(nn.Conv2d(10, 16, 3, padding=1), nn.ReLU(),
                                   nn.Conv2d(16, 16, 3, stride=2, padding=1), nn.ReLU(),
                                   nn.AdaptiveAvgPool2d((2, 3)), nn.Flatten())
        # Four visual vectors, ten tactile/state vectors, history and camera masks.
        self.head = nn.Sequential(nn.Linear(4*256 + 10*96 + 10*14 + 10 + 20, 128),
                                  nn.ReLU(), nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 6))

    def initialize_pretrained(self, weights):
        self.backbone.load_state_dict(weights, strict=True)
        with torch.no_grad():
            self.history_stem.weight.copy_(self.backbone.stem.weight.repeat(1, 9, 1, 1)/9.)

    def train(self, mode=True):
        super().train(mode)
        self.backbone.eval()
        return self

    def history_features(self, rgb, valid):
        """Oldest first, exactly nine slots; missing normalized input is zero."""
        if rgb.shape[1:] != (9, 3, 128, 128) or valid.shape != rgb.shape[:2]:
            raise ValueError('Expected nine RGB frames and one validity flag per slot')
        normalized = (rgb-self.backbone.mean[None])/self.backbone.std[None]
        normalized = torch.where(valid[:, :, None, None, None], normalized, 0.)
        x = self.history_stem(normalized.flatten(1, 2))
        x = F.relu(self.backbone.stem_norm(x))
        x = F.max_pool2d(same_pad(x, 3, 2, float('-inf')), 3, stride=2)
        # Frozen weights still propagate gradients to the trainable history stem.
        for block in self.backbone.blocks:
            x = block(x)
        return x

    def cache_current(self, x, batch_size=32):
        """Training optimization only: cache frozen 3-channel current-frame maps."""
        result = []
        with torch.no_grad():
            for source, camera in ((0, 0), (3, 1)):
                maps = x[source].new_zeros((len(x[source]), 512, 4, 4))
                ids = torch.nonzero(x[4][:, camera].bool(), as_tuple=True)[0]
                for ix in ids.split(batch_size):
                    maps[ix] = self.backbone(x[source][ix])
                result.append(maps)
        return tuple(result)

    def forward_windows(self, x, history_mask, current_maps=None):
        """Inputs are normalized by inputs(), shape [B,10,...]; images are RGB/255."""
        if history_mask.shape != x[0].shape[:2] or history_mask.shape[1] != 10:
            raise ValueError('Expected ten chronological slots')
        if not history_mask[:, -1].all():
            raise ValueError('Current observation is required')
        camera = x[4].clone()*history_mask[:, :, None]
        if self.training and self.contract['wrist_training_dropout']:
            keep = torch.rand(camera.shape[:2], device=camera.device) >= self.contract['wrist_training_dropout']
            camera[:, :, 1] *= keep
        features = []
        for view, source in enumerate((0, 3)):
            valid_now = camera[:, -1, view].bool()
            ids = torch.nonzero(valid_now, as_tuple=True)[0]
            now = x[0].new_zeros((len(history_mask), 256))
            if len(ids):
                if current_maps is None:
                    with torch.no_grad():
                        maps = self.backbone(x[source][ids, -1])
                else:
                    maps = current_maps[view][ids]
                now[ids] = self.current_projection[view](maps)
            valid_past = camera[:, :-1, view].bool()
            ids = torch.nonzero(valid_past.any(1), as_tuple=True)[0]
            past = torch.zeros_like(now)
            if len(ids):
                maps = self.history_features(x[source][ids, :-1], valid_past[ids])
                past[ids] = self.history_projection[view](maps)
            features.extend((now, past))
        touch = x[1].new_zeros((len(history_mask), 10, 96))
        touch[history_mask] = self.touch(x[1][history_mask])
        state = torch.where(history_mask[:, :, None], x[2], 0.)
        features.extend((touch.flatten(1), state.flatten(1), history_mask.float(), camera.flatten(1)))
        return self.head(torch.cat(features, dim=1))

    def forward(self, x, index, current_maps=None):
        if index.ndim != 2 or index.shape[1] != 10 or (index < -1).any() or (index >= len(x[0])).any():
            raise ValueError('Invalid history index')
        mask = index >= 0
        window = tuple(v[index.clamp_min(0)] for v in x)
        maps = None if current_maps is None else tuple(v[index[:, -1]] for v in current_maps)
        return self.forward_windows(window, mask, maps)


def predict(model, x, index, norm, current_maps=None, batch_size=32):
    model.eval()
    with torch.no_grad():
        values = [model(x, ix, current_maps).numpy() for ix in index.split(batch_size)]
    return (np.concatenate(values)*np.asarray(norm['delta_std'], np.float32)
            + np.asarray(norm['delta_mean'], np.float32))


def load_stack_policy(path):
    c = torch.load(path, map_location='cpu', weights_only=True)
    cfg = c['config']
    if cfg['version'] != VERSION or cfg['history_slots'] != SLOTS or cfg['period_ns'] != PERIOD_NS:
        raise ValueError('Incompatible current/stack checkpoint')
    model = CurrentStackPolicy(cfg['base_contract'])
    model.load_state_dict(c['state_dict'], strict=True)
    return model.eval(), cfg['normalization'], c


def run(plan_path, weights, output, steps=2000, seed=7, threads=2):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if steps < 1 or threads < 1:
        raise ValueError('Positive steps and threads required')
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.set_num_threads(threads); torch.use_deterministic_algorithms(True)
    plan = json.loads(Path(plan_path).read_text())
    data, manifests, idx, ep, ts = load_history(plan['training'])
    val, vm, vi, ve, vt = load_history(plan['validation'])
    contract = manifests[0]['contract']
    if vm[0]['contract'] != contract:
        raise ValueError('Contract mismatch')
    if {m['episode_id'] for m in manifests} & {m['episode_id'] for m in vm}:
        raise ValueError('Episode leakage')
    norm = normalization(data)
    x, vx = inputs(data, norm), inputs(val, norm)
    index, vindex = torch.as_tensor(idx), torch.as_tensor(vi)
    model = CurrentStackPolicy(contract)
    model.initialize_pretrained(torch.load(weights, map_location='cpu', weights_only=True))
    before = {k: v.clone() for k, v in model.backbone.state_dict().items()}
    stem_before = model.history_stem.weight.detach().clone()
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam([
        dict(params=list(model.history_stem.parameters()), lr=1e-4),
        dict(params=[p for n, p in model.named_parameters() if p.requires_grad and not n.startswith('history_stem.')], lr=1e-3)])
    output.mkdir(parents=True)
    config = dict(version=VERSION, base_contract=contract, normalization=norm, history_slots=10,
                  period_ns=PERIOD_NS, seed=seed, steps=steps, batch_size=32, device='cpu', cpu_threads=threads,
                  learning_rate=.001, history_stem_learning_rate=.0001,
                  train_episode_ids=[m['episode_id'] for m in manifests],
                  validation_episode_ids=[m['episode_id'] for m in vm],
                  source_samples_sha256=[m['samples_sha256'] for m in manifests],
                  validation_samples_sha256=[m['samples_sha256'] for m in vm],
                  weights_sha256=sha256(weights),
                  architecture='Current RGB3 frozen stem; past9 RGB27 trainable stem; shared frozen GN/residual suffix; no GRU',
                  history_stem_init='pretrained RGB kernel repeated 9 times and divided by 9; then optimized',
                  visual_projection='four independent 512->16 1x1, flatten4x4, LN256, tanh',
                  tactile_state='shared trainable two-layer tactile CNN per slot; flatten ten 96D features and ten 14D states',
                  fusion='2154 -> 128 -> 64 -> 6; includes 10 history flags and 20 camera flags',
                  image_normalization='RGB/255 then ImageNet mean/std per slot',
                  missing='zero after normalization; preserve fixed channel slots; gate absent branch after projection',
                  dropout='wrist 0.2 per window slot, before current/history branching; eval disabled',
                  cache='only frozen current image features cached; past9 stem/residual outputs recomputed every update',
                  selection='lowest validation normalized MSE among trained evaluations every100 steps',
                  objective='normalized action MSE; no keypoint auxiliary loss')
    (output/'config.json').write_text(json.dumps(config, indent=2)+'\n')
    (output/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    np.savez_compressed(output/'history_index.npz', train_index=idx, validation_index=vi,
                        train_episode=ep, validation_episode=ve, train_reference_ns=ts, validation_reference_ns=vt)
    started = time.monotonic()
    print('Preparing frozen current-frame cache; historical stem remains trainable.', flush=True)
    cx, cv = model.cache_current(x), model.cache_current(vx)
    target, vtarget = data['action'], val['action']
    y = torch.from_numpy((target-np.asarray(norm['delta_mean'], np.float32))/np.asarray(norm['delta_std'], np.float32))
    history, losses = [], []
    best, best_step = float('inf'), None

    def evaluate(step):
        nonlocal best, best_step
        pred, vp = predict(model, x, index, norm, cx), predict(model, vx, vindex, norm, cv)
        row = dict(step=step, elapsed_seconds=time.monotonic()-started,
                   train=scores(pred, target, norm), validation=scores(vp, vtarget, norm))
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
        loss = F.mse_loss(model(x, index[batch], cx), y[batch])
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite loss')
        optimizer.zero_grad(); loss.backward()
        nn.utils.clip_grad_norm_(trainable, 5.); optimizer.step()
        if step == 1 or step % 25 == 0:
            losses.append(dict(step=step, normalized_mse=float(loss.detach())))
            print(json.dumps(dict(progress_step=step, loss=float(loss.detach()), elapsed_seconds=time.monotonic()-started)), flush=True)
        if step % 100 == 0 or step == steps:
            pred, vp = evaluate(step)
    torch.save(dict(config=config, step=steps, state_dict=model.state_dict()), output/'last.pt')
    np.savez_compressed(output/'last_predictions.npz', train=pred, validation=vp, train_target=target,
                        validation_target=vtarget, validation_episode=ve, validation_reference_ns=vt)
    assert all(torch.equal(v, before[k]) for k, v in model.backbone.state_dict().items()), 'Frozen backbone changed'
    assert not torch.equal(stem_before, model.history_stem.weight), 'Historical stem did not learn'
    final_stem_change = float((model.history_stem.weight.detach()-stem_before).abs().max())
    model, reloaded_norm, _ = load_stack_policy(output/'best.pt')
    assert reloaded_norm == norm
    bp = predict(model, vx, vindex, norm, cv)
    best_row = next(h for h in history if h['step'] == best_step)
    np.testing.assert_allclose(scores(bp, vtarget, norm)['normalized_mse'], best_row['validation']['normalized_mse'], rtol=1e-6)
    check_ids = np.unique(np.concatenate([np.arange(min(4, len(vi))), np.flatnonzero((vi>=0).all(1))[:4]]))
    raw = predict(model, vx, vindex[check_ids], norm)
    np.testing.assert_allclose(raw, bp[check_ids], atol=1e-7, rtol=1e-5)
    np.savez_compressed(output/'best_validation_predictions.npz', prediction=bp, target=vtarget, episode=ve, reference_ns=vt)
    mean = target.mean(0)
    report = dict(config=config, seconds=time.monotonic()-started, samples=len(target), validation_samples=len(vtarget),
                  parameters=sum(p.numel() for p in model.parameters()), trainable_parameters=sum(p.numel() for p in trainable),
                  frozen_parameters=sum(p.numel() for p in model.backbone.parameters()), history=history, losses=losses,
                  best_step=best_step, best_validation=scores(bp, vtarget, norm), last_validation=history[-1]['validation'],
                  zero_baseline=scores(np.zeros_like(vtarget), vtarget, norm),
                  mean_baseline=scores(np.broadcast_to(mean, vtarget.shape), vtarget, norm),
                  per_episode={vm[i]['episode_id']: scores(bp[ve==i], vtarget[ve==i], norm) for i in range(len(vm))},
                  checks=dict(frozen_backbone_unchanged=True, history_stem_max_change=final_stem_change,
                              checkpoint_reload_metrics_match=True, raw_cache_max_action_difference=float(np.max(np.abs(raw-bp[check_ids])))),
                  best_sha256=sha256(output/'best.pt'), last_sha256=sha256(output/'last.pt'),
                  warning='Single seed, validation-selected model. Visual adaptation, fusion and temporal architecture all differ; no isolated GRU ablation or closed-loop result.')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=2000)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--threads', type=int, default=2)
    a = p.parse_args()
    run(a.plan, a.weights, a.output, a.steps, a.seed, a.threads)


if __name__ == '__main__':
    main()
