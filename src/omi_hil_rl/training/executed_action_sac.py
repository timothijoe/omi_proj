"""SAC variant that stores the action actually commanded after intervention.

This is a small simulation training bridge. The intended full-scale learner is
LeRobot HIL-SERL once its Tianji environment adapter is ready.
"""

from __future__ import annotations

import numpy as np
import torch.nn.functional as F
from stable_baselines3 import SAC
from stable_baselines3.common.buffers import ReplayBuffer

from omi_hil_rl.training.hil_replay import HILReplayBuffer


class ExecutedActionSAC(SAC):
    """Use the environment's post-arbitration action in off-policy replay.

    The OMI surrogate has action bounds [-1, 1], so SB3's normalized replay
    action uses the same units as ``info['executed_action']``. This class
    deliberately rejects other bounds until a conversion is implemented.
    """

    def _setup_model(self) -> None:
        super()._setup_model()
        low = np.asarray(self.action_space.low)
        high = np.asarray(self.action_space.high)
        if not np.allclose(low, -1.0) or not np.allclose(high, 1.0):
            raise ValueError("ExecutedActionSAC requires action bounds [-1, 1]")

    def _store_transition(
        self,
        replay_buffer: ReplayBuffer,
        buffer_action: np.ndarray,
        new_obs,
        reward: np.ndarray,
        dones: np.ndarray,
        infos: list[dict],
    ) -> None:
        executed = []
        for info in infos:
            if "executed_action" not in info:
                raise ValueError("environment did not report executed_action")
            action = np.asarray(info["executed_action"], dtype=np.float32)
            if action.shape != self.action_space.shape or not np.all(np.isfinite(action)):
                raise ValueError("invalid executed_action from environment")
            executed.append(action)
        super()._store_transition(
            replay_buffer, np.stack(executed), new_obs, reward, dones, infos
        )


class DemoRegularizedSAC(ExecutedActionSAC):
    """SAC with one behavioral-cloning actor update from human data per call."""

    def __init__(self, *args, bc_weight: float = 1.0, **kwargs):
        if not np.isfinite(bc_weight) or bc_weight < 0:
            raise ValueError("bc_weight must be nonnegative and finite")
        super().__init__(*args, **kwargs)
        self.bc_weight = float(bc_weight)
        self.bc_updates = 0

    def train(self, gradient_steps: int, batch_size: int = 64) -> None:
        super().train(gradient_steps, batch_size)
        replay = self.replay_buffer
        if self.bc_weight == 0 or not isinstance(replay, HILReplayBuffer) or not replay.human_mask[:replay.size()].any():
            return
        batch = replay.sample_human(batch_size, env=self._vec_normalize_env)
        predicted = self.actor(batch.observations, deterministic=True)
        loss = self.bc_weight * F.mse_loss(predicted, batch.actions)
        self.actor.optimizer.zero_grad()
        loss.backward()
        self.actor.optimizer.step()
        self.bc_updates += 1
