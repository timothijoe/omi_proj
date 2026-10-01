"""Lossless per-step provenance for the simulation HIL training loop."""

from __future__ import annotations

import json
from pathlib import Path

import gymnasium as gym
import numpy as np


class TransitionRecorder(gym.Wrapper):
    """Write policy, intervention and executed actions with both observations.

    The JSONL schema is intentionally explicit so offline conversion can check
    action provenance before loading demonstrations into another learner.
    """

    def __init__(self, env: gym.Env, path: Path):
        super().__init__(env)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("w", encoding="utf-8")
        self._episode = -1
        self._step = 0
        self._last_observation = None

    @staticmethod
    def _observation_to_json(observation: dict[str, np.ndarray]) -> dict[str, list]:
        return {key: np.asarray(value).tolist() for key, value in observation.items()}

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self._episode += 1
        self._step = 0
        self._last_observation = observation
        return observation, info

    def step(self, action, **kwargs):
        if self._last_observation is None:
            raise RuntimeError("reset must be called before step")
        observation, reward, terminated, truncated, info = self.env.step(action, **kwargs)
        record = {
            "episode": self._episode,
            "step": self._step,
            "observation": self._observation_to_json(self._last_observation),
            "policy_action": np.asarray(info["policy_action"]).tolist(),
            "human_action": None if info["human_action"] is None else np.asarray(info["human_action"]).tolist(),
            "executed_action": np.asarray(info["executed_action"]).tolist(),
            "commanded_joint_target_rad": np.asarray(info["commanded_joint_target_rad"]).tolist(),
            "action_source": info["action_source"],
            "reward": float(reward),
            "next_observation": self._observation_to_json(observation),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "model_kind": info["model_kind"],
            "task": info.get("task"),
            "tcp_error_m": info.get("tcp_error_m"),
        }
        self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._stream.flush()
        self._last_observation = observation
        self._step += 1
        return observation, reward, terminated, truncated, info

    def close(self):
        self._stream.close()
        self.env.close()
