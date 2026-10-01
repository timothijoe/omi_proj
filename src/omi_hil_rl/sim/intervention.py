"""Scripted intervention source for repeatable HIL training tests."""

from __future__ import annotations

from collections.abc import Callable

import gymnasium as gym
import numpy as np


Teacher = Callable[[dict[str, np.ndarray]], np.ndarray]


def joint_goal_teacher(goal_rad: np.ndarray, max_delta_rad: float) -> Teacher:
    """Return a proportional teacher for the surrogate joint reaching task."""
    goal = np.asarray(goal_rad, dtype=np.float64).copy()
    if goal.shape != (7,) or not np.all(np.isfinite(goal)) or max_delta_rad <= 0:
        raise ValueError("invalid goal or max_delta_rad")

    def act(observation: dict[str, np.ndarray]) -> np.ndarray:
        joints = np.asarray(observation["state"][:7], dtype=np.float64)
        return np.clip((goal - joints) / max_delta_rad, -1.0, 1.0).astype(np.float32)

    return act


class ScriptedInterventionWrapper(gym.Wrapper):
    """Let a scripted teacher override a policy action with a set probability.

    This tests the human-in-the-loop data path. It is not a human input device.
    """

    def __init__(self, env: gym.Env, teacher: Teacher, probability: float, seed: int = 0):
        super().__init__(env)
        self.teacher = teacher
        self.set_probability(probability)
        self.rng = np.random.default_rng(seed)
        self.last_observation: dict[str, np.ndarray] | None = None

    def set_probability(self, probability: float) -> None:
        if not np.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("intervention probability must be in [0, 1]")
        self.probability = float(probability)

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self.last_observation = observation
        return observation, info

    def step(self, action):
        if self.last_observation is None:
            raise RuntimeError("reset must be called before step")
        active = bool(self.rng.random() < self.probability)
        human_action = self.teacher(self.last_observation) if active else None
        observation, reward, terminated, truncated, info = self.env.step(
            action, intervention_active=active, human_action=human_action
        )
        self.last_observation = observation
        return observation, reward, terminated, truncated, info
