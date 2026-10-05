"""Streaming BC of adopted human commands; rewards are never training inputs."""
import argparse
import json
from pathlib import Path
import random

import numpy as np
import torch
from torch.nn import functional as F
from torch.utils.data import Dataset, DataLoader

from omi_hil_rl.hil.demo import DEMO_VERSION, read_demo_step
from omi_hil_rl.hil.exchange import atomic_json, atomic_torch
from omi_hil_rl.hil.networks import Actor, VERSION, load_actor
from .eef_bc_data import sha256
from .eef_bc_grid import GridProfile
from .transition_replay import _spaces, _array

PLAN_VERSION = "omi-human-demo-bc-plan-v1"
BC_VERSION = "omi-human-demo-bc-v1"


def dataset_for_plan(plan, split):
    if plan['version'] == PLAN_VERSION:
        return DemoDataset(plan, split)
    from .passive_bc import PLAN_VERSION as PASSIVE_PLAN_VERSION, PassiveDataset
    if plan['version'] == PASSIVE_PLAN_VERSION:
        return PassiveDataset(plan, split)
    raise ValueError('unsupported BC plan version; review-only previews are not training data')


def make_plan(directories, output, *, validation_episodes=1, seed=7, success_only=False):
    paths = set()
    for root in directories:
        root = Path(root)
        if (root / "conversion_pending.json").exists() or (root.parent.parent / "conversion_pending.json").exists():
            raise ValueError("dataset conversion is incomplete")
        if (root / "demo.json").exists():
            paths.add((root / "demo.json").resolve())
        else:
            paths.update(p.resolve() for p in root.glob("episodes/*/demo.json"))
    episodes, ids, contract = [], set(), None
    for path in sorted(paths):
        manifest = json.loads(path.read_text())
        if manifest["version"] != DEMO_VERSION:
            raise ValueError("unsupported demo schema")
        if not manifest["keep"] or not manifest["valid"] or not manifest["count"]:
            continue
        if success_only and manifest["operator_outcome"] != "success":
            continue
        if manifest["episode"] in ids:
            raise ValueError("duplicate episode ID")
        ids.add(manifest["episode"])
        contract = manifest["contract"] if contract is None else contract
        if manifest["contract"] != contract:
            raise ValueError("cannot mix observation/action/config contracts")
        if manifest["synthetic"] != (contract["config"]["transport"] == "fake"):
            raise ValueError("synthetic and real demo markers disagree")
        samples = [path.parent / f"{i:06d}.npz" for i in range(manifest["count"])]
        episodes.append(dict(path=str(path.parent), episode=manifest["episode"], count=manifest["count"],
            manifest_sha256=sha256(path), samples_sha256=[sha256(p) for p in samples]))
    if validation_episodes < 1 or len(episodes) <= validation_episodes:
        raise ValueError("need at least one training episode and one distinct validation episode")
    random.Random(seed).shuffle(episodes)
    plan = dict(version=PLAN_VERSION, contract=contract, seed=seed, success_only=success_only,
                training=episodes[validation_episodes:], validation=episodes[:validation_episodes],
                target="adopted_human_command_normalized", reward_used=False)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    atomic_json(output, plan)
    return plan


class DemoDataset(Dataset):
    """Index and manifests in RAM; at most requested samples are decoded."""
    def __init__(self, plan, split):
        if plan["version"] != PLAN_VERSION or split not in ("training", "validation"):
            raise ValueError("invalid BC plan/split")
        train_ids = {ep["episode"] for ep in plan["training"]}
        validation_ids = {ep["episode"] for ep in plan["validation"]}
        if not train_ids or not validation_ids or train_ids & validation_ids:
            raise ValueError("episode leakage or empty split")
        self.contract = plan["contract"]
        self.spaces, self.action_space = _spaces(self.contract)
        self.index, self.manifests = [], {}
        for episode in plan[split]:
            path = Path(episode["path"])
            if sha256(path / "demo.json") != episode["manifest_sha256"]:
                raise ValueError("demo manifest hash mismatch")
            manifest = json.loads((path / "demo.json").read_text())
            if (manifest["version"] != DEMO_VERSION or not manifest["keep"] or not manifest["valid"]
                    or manifest["contract"] != self.contract or manifest["count"] != episode["count"]
                    or manifest["episode"] != episode["episode"]):
                raise ValueError("demo does not match plan")
            if len(episode["samples_sha256"]) != manifest["count"]:
                raise ValueError("sample hash count mismatch")
            self.manifests[str(path)] = manifest
            previous = None
            for i, digest in enumerate(episode["samples_sha256"]):
                if sha256(path / f"{i:06d}.npz") != digest:
                    raise ValueError("demo sample hash mismatch")
                observation, nxt, action, metadata = read_demo_step(path, i, manifest)
                if not 0 < metadata["observation_time_ns"] < metadata["next_observation_time_ns"]:
                    raise ValueError("invalid demo chronology")
                if previous is not None and previous != metadata["observation_time_ns"]:
                    raise ValueError("demo timestamp discontinuity")
                previous = metadata["next_observation_time_ns"]
                self._check(observation)
                self._check(nxt)
                _array(action, self.action_space, "demo action")
                self.index.append((str(path), i))

    def _check(self, observation):
        if set(observation) != set(self.spaces.spaces):
            raise ValueError("observation key mismatch")
        for key, space in self.spaces.spaces.items():
            _array(observation[key], space, "observation." + key)
        if not np.all(observation["history_mask"]) or np.any(observation["state"][:, :7]):
            raise ValueError("invalid BC history/joint mask")
        if not np.all(observation["camera_mask"][:, 0]):
            raise ValueError("external RGB required")
        mode = self.contract["config"]["wrist_camera"]
        if mode == "required" and not np.all(observation["camera_mask"][:, 1]):
            raise ValueError("required wrist RGB absent")
        if mode == "off" and np.any(observation["camera_mask"][:, 1]):
            raise ValueError("unexpected wrist RGB")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        path, step = self.index[index]
        observation, _, action, _ = read_demo_step(path, step, self.manifests[path])
        return observation, action


def statistics(dataset):
    """Training-only streaming moments; action scales come from the contract."""
    sums = dict(tactile=np.zeros(10, np.float64), state=np.zeros(14, np.float64))
    squares = {k: np.zeros_like(v) for k, v in sums.items()}
    counts = dict(tactile=0, state=0)
    action_sum = np.zeros(6, np.float64)
    wrench_sum, wrench_square, wrench_count = np.zeros((2, 6)), np.zeros((2, 6)), np.zeros((2, 1))
    for i in range(len(dataset)):
        obs, action = dataset[i]
        touch = obs["tactile"].astype(np.float64).transpose(0, 2, 3, 1).reshape(-1, 10)
        state = obs["state"].astype(np.float64).reshape(-1, 14)
        for key, values in (("tactile", touch), ("state", state)):
            sums[key] += values.sum(0)
            squares[key] += np.square(values).sum(0)
            counts[key] += len(values)
        action_sum += action
        if 'wrench' in obs:
            for side in range(2):
                values = obs['wrench'][obs['wrench_mask'][:, side].astype(bool), side].astype(np.float64)
                wrench_sum[side] += values.sum(0)
                wrench_square[side] += np.square(values).sum(0)
                wrench_count[side] += len(values)
    result = {}
    for key, floor, shape in (("tactile", 1e-4, (1, 10, 1, 1)), ("state", 1e-3, (1, 14))):
        mean = sums[key] / counts[key]
        std = np.maximum(np.sqrt(np.maximum(squares[key] / counts[key] - mean * mean, 0)), floor)
        if key == "state":
            mean[:7], std[:7] = 0, 1
        result[key + "_mean"] = mean.reshape(shape).tolist()
        result[key + "_std"] = std.reshape(shape).tolist()
    if 'wrench' in dataset.contract['observations']:
        if np.any(wrench_count == 0):
            raise ValueError('no valid training wrench values on one finger')
        mean = wrench_sum / wrench_count
        std = np.maximum(np.sqrt(np.maximum(wrench_square / wrench_count - mean * mean, 0)), 1e-3)
        result.update(wrench_mean=mean.tolist(), wrench_std=std.tolist(), wrench_valid_counts=wrench_count[:, 0].astype(int).tolist())
    return result, action_sum / len(dataset)


@torch.inference_mode()
def metrics(actor, dataset, *, device="cpu", batch_size=32, baseline=None):
    total, squared, physical_squared = 0, 0., np.zeros(6, np.float64)
    moving_count, moving_squared = 0, 0.
    scale = np.asarray(dataset.contract["physical_action_scale"], np.float64)
    for obs, target in DataLoader(dataset, batch_size=batch_size, shuffle=False):
        if baseline is None:
            prediction = actor.sample({k: v.to(device) for k, v in obs.items()}, deterministic=True)[0].cpu().numpy()
        else:
            prediction = np.broadcast_to(baseline, target.shape)
        error = prediction - target.numpy()
        if not np.isfinite(error).all():
            raise ValueError("nonfinite BC prediction")
        squared += float(np.square(error).sum())
        physical_squared += np.square(error * scale).sum(0)
        moving = np.any(target.numpy() != 0, axis=1)
        moving_count += int(moving.sum())
        moving_squared += float(np.square(error[moving]).sum())
        total += len(target)
    return dict(samples=total, normalized_mse=squared / (total * 6),
                nonzero_samples=moving_count,
                nonzero_normalized_mse=moving_squared / (moving_count * 6) if moving_count else None,
                per_axis_rmse_m_rad=np.sqrt(physical_squared / total).tolist(),
                translation_rmse_mm=float(np.sqrt(physical_squared[:3].sum() / (total * 3)) * 1000),
                rotation_rmse_deg=float(np.degrees(np.sqrt(physical_squared[3:].sum() / (total * 3)))))


def train(plan_path, output, *, pretrained=None, steps=500, batch_size=32, learning_rate=1e-3,
          evaluate_every=50, seed=7, device="cpu"):
    if min(steps, batch_size, evaluate_every) < 1 or not np.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("invalid BC training parameters")
    plan = json.loads(Path(plan_path).read_text())
    train_data, validation_data = dataset_for_plan(plan, "training"), dataset_for_plan(plan, "validation")
    norm, action_mean = statistics(train_data)
    synthetic = plan["contract"]["config"]["transport"] == "fake"
    if not synthetic and pretrained is None:
        raise ValueError("real BC requires official --pretrained backbone weights")
    recipe = dict(encoder="synthetic-test" if synthetic else "current9stack", normalization=norm,
                  training_objective="bc_deterministic_normalized_command_mse", std_head="fixed_log_std_minus5")
    if 'wrench' in plan['contract']['observations']:
        recipe['wrench_history'] = True
        recipe['wrench_contract'] = plan['contract']['wrench']
    recipe['action_semantics'] = plan['contract']['action_semantics']
    if not synthetic:
        recipe.update(base_contract=GridProfile(plan["contract"]["config"]["wrist_camera"]).CONTRACT,
                      sdk_convention=plan["contract"]["config"]["sdk_convention"], pretrained_sha256=sha256(pretrained))
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    actor = Actor(recipe).to(device).eval()
    if not synthetic:
        actor.encoder.initialize_pretrained(torch.load(pretrained, map_location="cpu", weights_only=True))
    with torch.no_grad():
        actor.head[-1].weight[6:] = 0
        actor.head[-1].bias[6:] = -5.
    optimizer = torch.optim.Adam([p for p in actor.parameters() if p.requires_grad], lr=learning_rate)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "plan.json", plan)
    atomic_json(output / "recipe.json", recipe)
    atomic_json(output / 'training_config.json', dict(steps=steps, batch_size=batch_size,
        learning_rate=learning_rate, evaluate_every=evaluate_every, seed=seed, device=device,
        train_samples=len(train_data), validation_samples=len(validation_data),
        source_plan=str(Path(plan_path).resolve()), source_plan_sha256=sha256(plan_path),
        pretrained=None if pretrained is None else str(Path(pretrained).resolve())))
    history, best, best_step = [], float("inf"), None
    before_backbone = ({k: v.detach().clone() for k, v in actor.encoder.model.backbone.state_dict().items()}
                       if not synthetic else None)
    def evaluate(step):
        nonlocal best, best_step
        row = dict(step=step, training=metrics(actor, train_data, device=device, batch_size=batch_size),
                   validation=metrics(actor, validation_data, device=device, batch_size=batch_size))
        history.append(row)
        if row["validation"]["normalized_mse"] < best:
            best, best_step = row["validation"]["normalized_mse"], step
            atomic_torch(output / "actor.pt", dict(version=VERSION, recipe=recipe, contract=plan["contract"],
                actor=actor.state_dict(), updates=step, algorithm=BC_VERSION))
        atomic_json(output / "history.json", history)
        print(json.dumps(row), flush=True)
    evaluate(0)
    loader = DataLoader(train_data, batch_size=batch_size, shuffle=True)
    iterator = iter(loader)
    for step in range(1, steps + 1):
        try:
            obs, target = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            obs, target = next(iterator)
        prediction = actor.sample({k:v.to(device) for k,v in obs.items()}, deterministic=True)[0]
        loss = F.mse_loss(prediction, target.to(device))
        if not torch.isfinite(loss):
            raise ValueError("nonfinite BC loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in actor.parameters() if p.requires_grad], 5., error_if_nonfinite=True)
        optimizer.step()
        if step == 1 or step % 10 == 0:
            progress = dict(training_step=step, target_steps=steps, batch_loss=float(loss.detach()))
            atomic_json(output / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
        if step % evaluate_every == 0 or step == steps:
            evaluate(step)
    atomic_torch(output / "last.pt", dict(version=BC_VERSION, actor=actor.state_dict(), recipe=recipe,
        contract=plan["contract"], updates=steps, optimizer=optimizer.state_dict()))
    if before_backbone is not None and not all(torch.equal(v, before_backbone[k]) for k,v in actor.encoder.model.backbone.state_dict().items()):
        raise AssertionError("frozen visual backbone changed")
    best_actor, _, _ = load_actor(output / "actor.pt", plan["contract"], device)
    reloaded_metrics = metrics(best_actor, validation_data, device=device, batch_size=batch_size)
    best_row = next(row for row in history if row["step"] == best_step)
    if not np.isclose(reloaded_metrics["normalized_mse"], best_row["validation"]["normalized_mse"], rtol=1e-6, atol=1e-9):
        raise AssertionError("BC reload metrics mismatch")
    report = dict(version=BC_VERSION, contract=plan["contract"], synthetic=synthetic, reward_used=False,
        selection="lowest_validation_mse_including_initial", best_step=best_step,
        best_validation=reloaded_metrics, history=history,
        validation_zero_baseline=metrics(None, validation_data, baseline=np.zeros(6), batch_size=batch_size),
        validation_train_mean_baseline=metrics(None, validation_data, baseline=action_mean, batch_size=batch_size),
        train_episodes=[ep["episode"] for ep in plan["training"]], validation_episodes=[ep["episode"] for ep in plan["validation"]],
        pretrained_backbone_unchanged=before_backbone is not None, checkpoint_reload_match=True,
        evaluation="offline action imitation; no closed-loop insertion success measured")
    atomic_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    split = sub.add_parser("plan")
    split.add_argument("--demos", type=Path, required=True, action="append")
    split.add_argument("--output", type=Path, required=True)
    split.add_argument("--validation-episodes", type=int, default=1)
    split.add_argument("--seed", type=int, default=7)
    split.add_argument("--success-only", action="store_true")
    fit = sub.add_parser("train")
    fit.add_argument("--plan", type=Path, required=True)
    fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--pretrained", type=Path)
    fit.add_argument("--steps", type=int, default=500)
    fit.add_argument("--batch-size", type=int, default=32)
    fit.add_argument("--learning-rate", type=float, default=1e-3)
    fit.add_argument("--evaluate-every", type=int, default=50)
    fit.add_argument("--seed", type=int, default=7)
    fit.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    fit.add_argument("--threads", type=int, default=2)
    test = sub.add_parser("evaluate")
    test.add_argument("--plan", type=Path, required=True)
    test.add_argument("--checkpoint", type=Path, required=True)
    test.add_argument("--split", choices=("training", "validation"), default="validation")
    test.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    test.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if args.operation == "plan":
        result = make_plan(args.demos, args.output, validation_episodes=args.validation_episodes, seed=args.seed, success_only=args.success_only)
        print(json.dumps(dict(train_episodes=len(result["training"]), validation_episodes=len(result["validation"]))))
    else:
        if args.threads < 1:
            parser.error("threads must be positive")
        torch.set_num_threads(args.threads)
        if args.operation == "train":
            print(json.dumps(train(args.plan, args.output, pretrained=args.pretrained, steps=args.steps,
                batch_size=args.batch_size, learning_rate=args.learning_rate, evaluate_every=args.evaluate_every,
                seed=args.seed, device=args.device), indent=2))
        else:
            plan = json.loads(args.plan.read_text())
            dataset = dataset_for_plan(plan, args.split)
            actor, _, _ = load_actor(args.checkpoint, plan["contract"], args.device)
            print(json.dumps(metrics(actor, dataset, device=args.device), indent=2))


if __name__ == "__main__":
    main()
