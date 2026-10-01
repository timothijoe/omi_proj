"""Replay that deliberately mixes demonstration/intervention and online data."""

from __future__ import annotations

import numpy as np
from stable_baselines3.common.buffers import DictReplayBuffer


class HILReplayBuffer(DictReplayBuffer):
    """Sample a configurable share of human-commanded transitions.

    Online interventions are members of both logical streams. Imported offline
    demonstrations are members only of the demonstration stream. A single
    physical ring buffer stores the data while masks keep the streams distinct.
    """

    def __init__(self, *args, demo_fraction: float = 0.5, **kwargs):
        super().__init__(*args, **kwargs)
        if self.n_envs != 1:
            raise ValueError("HILReplayBuffer currently supports one environment")
        if not np.isfinite(demo_fraction) or not 0 <= demo_fraction <= 1:
            raise ValueError("demo_fraction must be in [0, 1]")
        self.demo_fraction = float(demo_fraction)
        self.human_mask = np.zeros(self.buffer_size, dtype=bool)
        self.online_mask = np.zeros(self.buffer_size, dtype=bool)

    def add(self, obs, next_obs, action, reward, done, infos):
        if len(infos) != 1 or infos[0].get("action_source") not in {"human", "policy"}:
            raise ValueError("each transition must report human or policy action_source")
        origin = infos[0].get("replay_origin", "online")
        if origin not in {"online", "offline_demo"} or (origin == "offline_demo" and infos[0]["action_source"] != "human"):
            raise ValueError("offline_demo replay origin requires a human action")
        self.human_mask[self.pos] = infos[0]["action_source"] == "human"
        self.online_mask[self.pos] = origin == "online"
        super().add(obs, next_obs, action, reward, done, infos)

    def stream_counts(self) -> dict[str, int]:
        size = self.size()
        return {
            "online": int(np.count_nonzero(self.online_mask[:size])),
            "demonstration": int(np.count_nonzero(self.human_mask[:size])),
            "offline_demonstration": int(np.count_nonzero(self.human_mask[:size] & ~self.online_mask[:size])),
        }

    def sample_partition_indices(self, batch_size: int) -> tuple[np.ndarray, np.ndarray]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        size = self.size()
        if size == 0:
            raise RuntimeError("cannot sample an empty replay buffer")
        demo_indices = np.flatnonzero(self.human_mask[:size])
        online_indices = np.flatnonzero(self.online_mask[:size])
        demo_count = int(round(batch_size * self.demo_fraction)) if demo_indices.size else 0
        if not online_indices.size:
            demo_count = batch_size
        if not demo_indices.size:
            demo_count = 0
        demo = np.random.choice(demo_indices, size=demo_count, replace=True)
        online = np.random.choice(online_indices, size=batch_size - demo_count, replace=True)
        return demo, online

    def sample_indices(self, batch_size: int) -> np.ndarray:
        human, online = self.sample_partition_indices(batch_size)
        indices = np.concatenate((human, online))
        np.random.shuffle(indices)
        return indices

    def sample(self, batch_size: int, env=None):
        return self._get_samples(self.sample_indices(batch_size), env=env)

    def sample_human(self, batch_size: int, env=None):
        indices = np.flatnonzero(self.human_mask[:self.size()])
        if indices.size == 0:
            raise RuntimeError("no human transitions available")
        chosen = np.random.choice(indices, size=batch_size, replace=True)
        return self._get_samples(chosen, env=env)
