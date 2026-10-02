"""Train and evaluate a SAC smoke policy with scripted interventions.

This validates the online HIL data path in simulation. It does not establish
real-robot policy quality or reproduce the full LeRobot HIL-SERL learner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback

from omi_hil_rl.sim.intervention import ScriptedInterventionWrapper, joint_goal_teacher
from omi_hil_rl.sim.tianji_a_reach import TianjiAReachEnv
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv
from omi_hil_rl.training.executed_action_sac import DemoRegularizedSAC
from omi_hil_rl.training.demo_import import import_human_demonstrations
from omi_hil_rl.training.hil_replay import HILReplayBuffer
from omi_hil_rl.training.disk_replay import DiskHILReplayBuffer
from omi_hil_rl.training.recording import TransitionRecorder


def save_policy_checkpoint(model, path):
    """Keep policy archives portable; disk replay is restored separately."""
    if not isinstance(model.replay_buffer, DiskHILReplayBuffer):
        model.save(path)
        return
    original = model.replay_buffer_class, model.replay_buffer_kwargs, model.buffer_size
    try:
        # SB3 allocates replay during load even for inference. Do not serialize
        # a disk directory or a large capacity into a portable policy archive.
        model.replay_buffer_class = HILReplayBuffer
        model.replay_buffer_kwargs = {"demo_fraction": model.replay_buffer.demo_fraction}
        model.buffer_size = 1
        model.save(path)
    finally:
        model.replay_buffer_class, model.replay_buffer_kwargs, model.buffer_size = original


class InterventionSchedule(BaseCallback):
    def __init__(self, wrapper: ScriptedInterventionWrapper, demonstration_steps: int, later_probability: float):
        super().__init__()
        self.wrapper = wrapper
        self.demonstration_steps = demonstration_steps
        self.later_probability = later_probability
        self.interventions = 0

    def _on_step(self) -> bool:
        self.interventions += sum(info.get("action_source") == "human" for info in self.locals["infos"])
        probability = 1.0 if self.num_timesteps < self.demonstration_steps else self.later_probability
        self.wrapper.set_probability(probability)
        return True


class EvaluationTrace(BaseCallback):
    """Measure policy improvement without interventions on fixed reset seeds."""

    def __init__(self, *, scene: Path | None, episodes: int, seed: int, interval: int, output_dir: Path):
        super().__init__()
        self.scene = scene
        self.episodes = episodes
        self.seed = seed
        self.interval = interval
        self.output_dir = output_dir
        self.records: list[dict] = []
        self._initial_actor = None

    def _on_training_start(self) -> None:
        self._initial_actor = torch.nn.utils.parameters_to_vector(self.model.actor.parameters()).detach().clone()
        self._record(0)

    def _record(self, step: int) -> None:
        actor = torch.nn.utils.parameters_to_vector(self.model.actor.parameters()).detach()
        record = {
            "step": step,
            **evaluate(self.model, self.episodes, seed=self.seed, scene=self.scene),
            "actor_parameter_l2_change": float(torch.linalg.vector_norm(actor - self._initial_actor).item()),
            "sac_updates": int(self.model._n_updates),
            "bc_updates": int(self.model.bc_updates),
            "entropy_coefficient": float(torch.exp(self.model.log_ent_coef).detach().item()),
        }
        self.records.append(record)
        with (self.output_dir / "policy_progress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        save_policy_checkpoint(self.model, self.output_dir / f"policy_step_{step}.zip")

    def _on_step(self) -> bool:
        if self.num_timesteps % self.interval == 0 and self.num_timesteps < self.model._total_timesteps:
            self._record(self.num_timesteps)
        return True

    def _on_training_end(self) -> None:
        self._record(self.num_timesteps)


def make_env(scene: Path | None = None, **kwargs):
    return TianjiAReachEnv(scene=scene, **kwargs) if scene is not None else TianjiSurrogateEnv(**kwargs)


def evaluate(model: DemoRegularizedSAC, episodes: int, seed: int = 1000, scene: Path | None = None) -> dict[str, float]:
    env = make_env(scene, reset_noise_rad=0.03)
    successes = 0
    lengths = []
    returns = []
    final_errors = []
    try:
        for episode in range(episodes):
            obs, _ = env.reset(seed=seed + episode)
            episode_return = 0.0
            for step in range(env.max_steps):
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                episode_return += reward
                if terminated or truncated:
                    successes += int(terminated)
                    lengths.append(step + 1)
                    returns.append(episode_return)
                    final_errors.append(info["tcp_error_m"])
                    break
    finally:
        env.close()
    return {
        "success_rate": successes / episodes,
        "mean_steps": float(np.mean(lengths)),
        "mean_return": float(np.mean(returns)),
        "mean_final_tcp_error_m": float(np.mean(final_errors)),
    }


def train(
    *,
    steps: int,
    demonstration_steps: int,
    later_intervention_probability: float,
    evaluation_episodes: int,
    output_dir: Path,
    seed: int,
    bc_weight: float = 10.0,
    scene: Path | None = None,
    demo_recording: Path | None = None,
    evaluation_interval: int = 300,
    entropy_initial: float = 1.0,
    replay_backend: str = "memory",
    replay_capacity: int | None = None,
    replay_directory: Path | None = None,
    replay_prefetch: bool = True,
) -> dict:
    if steps < 1 or not 0 <= demonstration_steps <= steps or evaluation_episodes < 1:
        raise ValueError("invalid step or episode count")
    if not 0 <= later_intervention_probability <= 1:
        raise ValueError("later intervention probability must be in [0, 1]")
    if evaluation_interval < 1:
        raise ValueError("evaluation_interval must be positive")
    if not np.isfinite(entropy_initial) or entropy_initial <= 0:
        raise ValueError("entropy_initial must be positive and finite")
    if replay_backend not in {"memory", "disk"}:
        raise ValueError("replay_backend must be memory or disk")
    if replay_capacity is not None and replay_capacity < 1:
        raise ValueError("replay_capacity must be positive")
    torch.set_num_threads(1)
    base = make_env(scene, reward_mode="progress", reset_noise_rad=0.03)
    teacher = joint_goal_teacher(base.goal_rad, base.max_delta_rad)
    intervention_env = ScriptedInterventionWrapper(base, teacher, probability=1.0, seed=seed)
    callback = InterventionSchedule(intervention_env, demonstration_steps, later_intervention_probability)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "policy_progress.jsonl").write_text("")
    env = TransitionRecorder(intervention_env, output_dir / "transitions.jsonl")
    model = None
    try:
        demo_lines = sum(1 for _ in demo_recording.open(encoding="utf-8")) if demo_recording else 0
        replay_kwargs = {"demo_fraction": 0.5}
        if replay_backend == "disk":
            replay_kwargs.update(directory=replay_directory or output_dir / "replay", prefetch=replay_prefetch)
        model = DemoRegularizedSAC(
            "MultiInputPolicy",
            env,
            seed=seed,
            device="cpu",
            buffer_size=replay_capacity if replay_capacity is not None else max(1000, steps + demo_lines + 1),
            replay_buffer_class=DiskHILReplayBuffer if replay_backend == "disk" else HILReplayBuffer,
            replay_buffer_kwargs=replay_kwargs,
            learning_starts=min(100, max(1, steps // 4)),
            batch_size=64,
            train_freq=1,
            gradient_steps=1,
            policy_kwargs={"net_arch": [64, 64]},
            bc_weight=bc_weight,
            ent_coef=f"auto_{entropy_initial}",
            verbose=0,
        )
        imported_demonstrations = (
            import_human_demonstrations(model, demo_recording, base.model_kind) if demo_recording else 0
        )
        trace = EvaluationTrace(
            scene=scene, episodes=evaluation_episodes, seed=1000 + seed * 100,
            interval=evaluation_interval, output_dir=output_dir,
        )
        model.learn(total_timesteps=steps, callback=[callback, trace])
        replay_counts = model.replay_buffer.stream_counts()
        metrics = {
            "training_steps": model.num_timesteps,
            "scripted_intervention_steps": callback.interventions,
            "replay_size": model.replay_buffer.size(),
            "imported_human_demonstrations": imported_demonstrations,
            "replay_streams": replay_counts,
            "initial_policy": trace.records[0],
            "final_policy": trace.records[-1],
            **{key: trace.records[-1][key] for key in ("success_rate", "mean_steps", "mean_return", "mean_final_tcp_error_m")},
            "model_kind": base.model_kind,
            "task": base.task,
            "scene": str(scene.resolve()) if scene else None,
            "training_backend": "stable_baselines3_sac_with_demo_bc" if bc_weight else "stable_baselines3_sac",
            "bc_weight": bc_weight,
            "entropy_initial": entropy_initial,
            "sac_updates": model._n_updates,
            "bc_updates": model.bc_updates,
            "replay_backend": replay_backend,
            "replay_capacity": model.replay_buffer.buffer_size,
        }
        save_policy_checkpoint(model, output_dir / "policy.zip")
        if replay_backend == "disk":
            metrics["replay_storage"] = model.replay_buffer.storage_stats()
            metrics["replay_checkpoint"] = str(model.replay_buffer.checkpoint())
        else:
            model.save_replay_buffer(output_dir / "replay.pkl")
        (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        return metrics
    finally:
        try:
            if model is not None and isinstance(model.replay_buffer, DiskHILReplayBuffer):
                model.replay_buffer.close()
        finally:
            env.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--demonstration-steps", type=int, default=250)
    parser.add_argument("--later-intervention-probability", type=float, default=0.1)
    parser.add_argument("--evaluation-episodes", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("data/sim_runs/latest"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bc-weight", type=float, default=10.0)
    parser.add_argument("--scene", type=Path, help="External cooking project MJCF; selects A-arm TCP reach")
    parser.add_argument("--demo-recording", type=Path, help="JSONL from keyboard_teleop to seed human replay")
    parser.add_argument("--evaluation-interval", type=int, default=300, help="Steps between fixed-seed policy audits")
    parser.add_argument("--entropy-initial", type=float, default=1.0, help="Initial automatic SAC entropy coefficient")
    parser.add_argument("--replay-backend", choices=("memory", "disk"), default="memory")
    parser.add_argument("--replay-capacity", type=int, help="Fixed ring capacity; oldest transitions are overwritten")
    parser.add_argument("--replay-directory", type=Path, help="Empty directory for disk arrays; defaults to OUTPUT_DIR/replay")
    parser.add_argument("--no-replay-prefetch", action="store_true", help="Disable background disk batch prefetch")
    args = parser.parse_args()
    print(json.dumps(train(
        steps=args.steps,
        demonstration_steps=args.demonstration_steps,
        later_intervention_probability=args.later_intervention_probability,
        evaluation_episodes=args.evaluation_episodes,
        output_dir=args.output_dir,
        seed=args.seed,
        bc_weight=args.bc_weight,
        scene=args.scene,
        demo_recording=args.demo_recording,
        evaluation_interval=args.evaluation_interval,
        entropy_initial=args.entropy_initial,
        replay_backend=args.replay_backend,
        replay_capacity=args.replay_capacity,
        replay_directory=args.replay_directory,
        replay_prefetch=not args.no_replay_prefetch,
    ), indent=2))


if __name__ == "__main__":
    main()
