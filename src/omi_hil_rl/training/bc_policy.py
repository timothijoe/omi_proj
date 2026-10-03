"""Small multimodal behavior-cloning policy, explicitly shadow-only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn

from .bag_bc_data import ARRAYS, CONTRACT, sha256


class Policy(nn.Module):
    def __init__(self):
        super().__init__()
        self.rgb = nn.Sequential(nn.Conv2d(3, 8, 5, stride=4, padding=2), nn.ReLU(),
                                 nn.Conv2d(8, 16, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4,4)), nn.Flatten())
        self.touch = nn.Sequential(nn.Conv2d(10, 16, 3, padding=1), nn.ReLU(),
                                   nn.Conv2d(16, 16, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((2,3)), nn.Flatten())
        self.head = nn.Sequential(nn.Linear(16*16+16*6+19, 128), nn.ReLU(), nn.Linear(128,64), nn.ReLU(), nn.Linear(64,7))

    def forward(self, rgb, tactile, state):
        return self.head(torch.cat((self.rgb(rgb), self.touch(tactile), state), dim=1))


def load_dataset(paths):
    parts, manifests = [], []
    for path in paths:
        path = Path(path)
        m = json.loads((path/"manifest.json").read_text())
        if m["contract"] != CONTRACT or sha256(path/"samples.npz") != m["samples_sha256"]:
            raise ValueError("Dataset contract/hash mismatch")
        with np.load(path/"samples.npz", allow_pickle=False) as src:
            part={k: src[k].copy() for k in (*ARRAYS, "action")}
        n=len(part["action"])
        shapes=dict(rgb=(n,3,128,128),tactile=(n,10,16,24),state=(n,19),action=(n,7))
        if n<2 or any(part[k].shape != shape or not np.isfinite(part[k]).all() for k,shape in shapes.items()):
            raise ValueError("Invalid dataset shapes/nonfinite values")
        if part["rgb"].dtype != np.uint8:
            raise ValueError("RGB must be uint8")
        parts.append(part)
        manifests.append(m)
    ids = [m["episode_id"] for m in manifests]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate episodes")
    return {k: np.concatenate([a[k] for a in parts]) for k in parts[0]}, manifests


def normalization(data):
    delta = data["action"]-data["state"][:,:7]
    return dict(tactile_mean=data["tactile"].mean(axis=(0,2,3), keepdims=True).tolist(),
                tactile_std=np.maximum(data["tactile"].std(axis=(0,2,3), keepdims=True), 1e-4).tolist(),
                state_mean=data["state"].mean(axis=0, keepdims=True).tolist(),
                state_std=np.maximum(data["state"].std(axis=0, keepdims=True), 1e-3).tolist(),
                delta_mean=delta.mean(axis=0, keepdims=True).tolist(),
                delta_std=np.maximum(delta.std(axis=0, keepdims=True), 1e-3).tolist())


def inputs(data, norm):
    return (torch.as_tensor(data["rgb"], dtype=torch.float32)/255.,
            torch.as_tensor((data["tactile"]-np.asarray(norm["tactile_mean"], dtype=np.float32))/np.asarray(norm["tactile_std"], dtype=np.float32)),
            torch.as_tensor((data["state"]-np.asarray(norm["state_mean"], dtype=np.float32))/np.asarray(norm["state_std"], dtype=np.float32)))


def predict(model, norm, data):
    with torch.inference_mode():
        result = model(*inputs(data, norm)).numpy()
    return data["state"][:,:7]+result*np.asarray(norm["delta_std"], dtype=np.float32)+np.asarray(norm["delta_mean"], dtype=np.float32)


def metrics(model, norm, data, mean_target):
    pred = predict(model, norm, data)
    return dict(rmse_rad=float(np.sqrt(np.mean((pred-data["action"])**2))),
                per_joint_rmse_rad=np.sqrt(np.mean((pred-data["action"])**2, axis=0)).tolist(),
                hold_q_rmse_rad=float(np.sqrt(np.mean((data["state"][:,:7]-data["action"])**2))),
                constant_target_rmse_rad=float(np.sqrt(np.mean((mean_target-data["action"])**2))))


def train(train_paths, output, *, val_paths=(), overfit=False, steps=500, seed=7, batch_size=32):
    if steps < 1 or batch_size < 1:
        raise ValueError("Positive steps and batch size required")
    if not val_paths and not overfit:
        raise ValueError("Provide held-out --validation episodes, or explicitly use --overfit-smoke")
    if val_paths and overfit:
        raise ValueError("Do not mix held-out validation and overfit-smoke")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refuse to overwrite training run")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    data, manifests = load_dataset(train_paths)
    val, val_manifests = load_dataset(val_paths) if val_paths else (None, [])
    if {m["episode_id"] for m in manifests} & {m["episode_id"] for m in val_manifests}:
        raise ValueError("Train/validation episode leakage")
    norm = normalization(data)
    model = Policy()
    x = inputs(data, norm)
    y = torch.as_tensor(((data["action"]-data["state"][:,:7])-np.asarray(norm["delta_mean"], dtype=np.float32))/np.asarray(norm["delta_std"], dtype=np.float32))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    baseline = data["action"].mean(axis=0)
    initial = metrics(model, norm, data, baseline)
    output.mkdir(parents=True)
    losses, started = [], time.monotonic()
    for step in range(steps):
        idx = torch.randint(len(y), (min(batch_size, len(y)),))
        model.train()
        loss = nn.functional.mse_loss(model(*(v[idx] for v in x)), y[idx])
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite training loss")
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.)
        optimizer.step()
        if step % 25 == 0 or step == steps-1:
            losses.append(dict(step=step+1, normalized_mse=float(loss.detach())))
    model.eval()
    final = metrics(model, norm, data, baseline)
    validation = None if val is None else metrics(model, norm, val, baseline)
    checkpoint = dict(contract=CONTRACT, normalization=norm, state_dict=model.state_dict(),
                      architecture="small_rgb_tactile_cnn_v1", training_episode_ids=[m["episode_id"] for m in manifests],
                      mode="overfit_smoke_not_generalization" if overfit else "episode_held_out", seed=seed)
    torch.save(checkpoint, output/"policy.pt")
    report = dict(mode=checkpoint["mode"], steps=steps, seed=seed, samples=len(y), validation_samples=0 if val is None else len(val["action"]),
                  train_episode_ids=checkpoint["training_episode_ids"], validation_episode_ids=[m["episode_id"] for m in val_manifests],
                  initial=initial, final=final, validation=validation, seconds=time.monotonic()-started,
                  normalization=norm, contract=CONTRACT, losses=losses, torch_version=str(torch.__version__),
                  checkpoint_sha256=sha256(output/"policy.pt"),
                  warning="Not a deployable robot controller; assumed action semantics; bag outcome unverified")
    (output/"report.json").write_text(json.dumps(report, indent=2))
    np.savez_compressed(output/"train_predictions.npz", prediction=predict(model,norm,data), target=data["action"])
    return report


def load_policy(path):
    torch.set_num_threads(2)
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint["contract"] != CONTRACT or checkpoint["architecture"] != "small_rgb_tactile_cnn_v1":
        raise ValueError("Incompatible policy contract")
    model = Policy()
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()
    return model, checkpoint["normalization"], checkpoint


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train", nargs="+", type=Path, required=True)
    p.add_argument("--validation", nargs="+", type=Path, default=[])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--overfit-smoke", action="store_true")
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--seed", type=int, default=7)
    a=p.parse_args()
    r=train(a.train, a.output, val_paths=a.validation, overfit=a.overfit_smoke, steps=a.steps, seed=a.seed)
    print(json.dumps({k:r[k] for k in ("mode","samples","steps","initial","final","validation","seconds")}, indent=2))


if __name__ == "__main__":
    main()
