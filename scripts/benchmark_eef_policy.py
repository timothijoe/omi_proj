#!/usr/bin/env python3
"""Measure CPU or CUDA batch-one history policies on real, complete validation windows.

Includes in-memory normalization/tensor creation, forward, action denormalization.
Excludes image decoding/ROI, ROS transport, observation alignment and model loading.
Streaming mode reuses nine fused history features, but recomputes the current
frame's two images, tactile features, fusion and all ten GRU updates each call.
"""
import argparse
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

from omi_hil_rl.training.eef_bc_data import sha256
from omi_hil_rl.training.eef_bc_policy import inputs
from omi_hil_rl.training.eef_bc_history import load_history, load_history_policy
from omi_hil_rl.training.eef_bc_resnet import load_resnet_history
from omi_hil_rl.training.eef_bc_stack import load_stack_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--cnn', type=Path, required=True)
    parser.add_argument('--resnet', type=Path, required=True)
    parser.add_argument('--stack', type=Path, help='Optional current+past9 model without GRU')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=300)
    parser.add_argument('--warmup', type=int, default=20)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.repeats < 1 or args.warmup < 1:
        raise ValueError('Positive repeats/warmup required')
    device = torch.device(args.device)
    if device.type == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA requested but unavailable')
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    models = {'cnn': load_history_policy(args.cnn), 'resnet10': load_resnet_history(args.resnet)}
    if args.stack:
        models['current9stack'] = load_stack_policy(args.stack)
    plan = json.loads(args.plan.read_text())
    data, manifests, indices, _, _ = load_history(plan['validation'])
    complete = np.flatnonzero((indices >= 0).all(axis=1))
    selected = complete[np.linspace(0, len(complete)-1, min(32, len(complete)), dtype=int)]
    windows = [{key: value[indices[i]].copy() for key, value in data.items() if key != 'action'}
               for i in selected]
    current = [{key: value[-1:].copy() for key, value in window.items()} for window in windows]
    index = torch.arange(10, device=device)[None]
    mask = torch.ones(1, 10, dtype=torch.bool, device=device)
    cache = {}
    timings = {(name, mode): [] for name in ('cnn', 'resnet10') for mode in ('full_history', 'cached_history')}
    if args.stack:
        timings['current9stack', 'current_and_history'] = []
    max_error = {}
    cpu_reference = {}
    device_error = {}
    def prepare(data, norm):
        return tuple(v.to(device) for v in inputs(data, norm))

    with torch.inference_mode():
        if device.type == 'cuda':
            for name, (model, norm, _) in models.items():
                cpu_reference[name] = np.concatenate([
                    model(inputs(window, norm), index.cpu()).numpy() for window in windows])
        for name, (model, norm, _) in models.items():
            model.to(device).eval()
            if name != 'current9stack':
                cache[name] = [model.encode(prepare(window, norm))[None] for window in windows]

        def infer(name, mode, i):
            model, norm, _ = models[name]
            if mode in ('full_history', 'current_and_history'):
                pred = model(prepare(windows[i], norm), index)
            else:
                features = cache[name][i].clone()
                features[:, -1] = model.encode(prepare(current[i], norm))
                pred = model.from_features(features, mask)
            return (pred.cpu().numpy()[0]*np.asarray(norm['delta_std'], np.float32).reshape(6)
                    + np.asarray(norm['delta_mean'], np.float32).reshape(6))

        if device.type == 'cuda':
            for name, (model, norm, _) in models.items():
                actual = np.concatenate([model(prepare(w, norm), index).cpu().numpy() for w in windows])
                expected = cpu_reference[name]
                np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)
                diff = np.abs(actual-expected)
                action_diff = diff*np.asarray(norm['delta_std'], np.float32)
                device_error[name] = dict(max_normalized_difference=float(diff.max()),
                    max_translation_difference_m=float(action_diff[:, :3].max()),
                    max_rotation_difference_rad=float(action_diff[:, 3:].max()))
        for name in ('cnn', 'resnet10'):
            errors = []
            for i in range(len(windows)):
                full = infer(name, 'full_history', i)
                cached = infer(name, 'cached_history', i)
                np.testing.assert_allclose(full, cached, atol=1e-7, rtol=1e-5)
                errors.append(float(np.max(np.abs(full-cached))))
            max_error[name] = max(errors)
        print('Raw and cached predictions agree; warming up.', flush=True)
        for j in range(args.warmup):
            for name, mode in timings:
                infer(name, mode, j % len(windows))
        # Interleave paths to reduce bias from changing CPU load/temperature.
        rng = np.random.default_rng(42)
        keys = list(timings)
        for j in range(args.repeats):
            for k in rng.permutation(len(keys)):
                name, mode = keys[k]
                if device.type == 'cuda':
                    torch.cuda.synchronize()
                start = time.perf_counter_ns()
                infer(name, mode, j % len(windows))
                if device.type == 'cuda':
                    torch.cuda.synchronize()
                timings[name, mode].append((time.perf_counter_ns()-start)/1e6)
            if (j+1) % 100 == 0:
                print(f'{j+1}/{args.repeats} measurements per path', flush=True)
    stats = {}
    for (name, mode), values in timings.items():
        stats.setdefault(name, {})[mode] = dict(mean_ms=float(np.mean(values)),
            p50_ms=float(np.percentile(values, 50)), p95_ms=float(np.percentile(values, 95)),
            p99_ms=float(np.percentile(values, 99)), max_ms=max(values),
            min_ms=min(values), measurements_ms=values)
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), platform.processor())
    report = dict(cpu=cpu, torch_version=str(torch.__version__), device=str(device), dtype='float32',
                  torch_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                  deterministic_algorithms=True, batch_size=1, history_slots=10, cameras=2,
                  image_shape=[3, 128, 128], repeats=args.repeats, warmup=args.warmup,
                  windows=len(windows), validation_reference_indices=selected.tolist(),
                  validation_sample_hashes=[m['samples_sha256'] for m in manifests],
                  checkpoint_hashes=dict(cnn=sha256(args.cnn), resnet10=sha256(args.resnet)),
                  cuda_version=torch.version.cuda,
                  gpu=torch.cuda.get_device_name() if device.type == 'cuda' else None,
                  cudnn_benchmark=False, tf32=False,
                  cpu_cuda_prediction_check=device_error,
                  raw_cached_max_action_difference=max_error,
                  includes='CPU input normalization/tensor construction, host-to-device copies when CUDA, forward, output to CPU, action denormalization; CUDA synchronized',
                  excludes='Model loading, camera exposure, decoding, ROI/resize, ROS, alignment, actuation; not end-to-end latency',
                  cached_history='Nine prior fused features reused; current two camera images encoded each call; ten GRU steps replayed',
                  online_status='CNN online implementation already caches fused features. ResNet cached mode is a benchmark, not online integration.',
                  results=stats)
    if args.stack:
        report['checkpoint_hashes']['current9stack'] = sha256(args.stack)
        report['current9stack'] = 'Both current RGB3 and past9 RGB27 recomputed per view; no feature cache, no GRU; offline benchmark only'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({n: {m: {k: v for k, v in s.items() if k != 'measurements_ms'}
                         for m, s in modes.items()} for n, modes in stats.items()}, indent=2))


if __name__ == '__main__':
    main()
