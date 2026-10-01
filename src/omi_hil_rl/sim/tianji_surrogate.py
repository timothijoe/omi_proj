"""Seven-joint MuJoCo fixture for testing the OMI HIL control contract.

The bundled MJCF is deliberately not a calibrated Tianji robot model.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import gymnasium as gym
import mujoco
import numpy as np


JOINT_NAMES = tuple(f"joint{i}" for i in range(1, 8))
ACTUATOR_NAMES = tuple(f"servo{i}" for i in range(1, 8))


class TianjiSurrogateEnv(gym.Env):
    """Gym environment with one common action path for policy and human input.

    Actions are normalized joint increments in [-1, 1]. Each component maps
    to ``max_delta_rad`` radians before being bounded by MJCF joint limits.
    ``info['executed_action']`` is the normalized *commanded* increment after
    limits, not a measurement of motion achieved during the physics step.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        max_delta_rad: float = 0.04,
        control_period_s: float = 0.1,
        max_steps: int = 80,
        goal_rad: tuple[float, ...] = (0.25, -0.15, 0.1, 0.0, 0.0, 0.0, 0.0),
        success_tolerance_rad: float = 0.06,
        reward_mode: str = "sparse",
        reset_noise_rad: float = 0.0,
        model_path: Path | str | None = None,
        joint_names: tuple[str, ...] = JOINT_NAMES,
        actuator_names: tuple[str, ...] = ACTUATOR_NAMES,
        tcp_site_name: str = "tcp",
        task: str = "joint",
        success_tolerance_m: float = 0.035,
        model_kind: str = "uncalibrated_7dof_surrogate",
    ) -> None:
        super().__init__()
        if model_path is None:
            model_path = files("omi_hil_rl.sim").joinpath("assets/tianji_7dof_surrogate.xml")
        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)
        self.joint_ids = np.asarray(
            [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in joint_names],
            dtype=int,
        )
        self.actuator_ids = np.asarray(
            [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, name) for name in actuator_names],
            dtype=int,
        )
        if len(joint_names) != 7 or len(actuator_names) != 7 or np.any(self.joint_ids < 0) or np.any(self.actuator_ids < 0):
            raise ValueError("MJCF must provide seven named joints and actuators")
        self.qpos_ids = self.model.jnt_qposadr[self.joint_ids]
        self.qvel_ids = self.model.jnt_dofadr[self.joint_ids]
        self.joint_limits = self.model.jnt_range[self.joint_ids].copy()
        self.tcp_site_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, tcp_site_name)
        if self.tcp_site_id < 0:
            raise ValueError(f"MJCF is missing TCP site {tcp_site_name}")

        ticks = control_period_s / self.model.opt.timestep
        if not np.isfinite(ticks) or ticks < 1 or not np.isclose(ticks, round(ticks), atol=1e-9):
            raise ValueError("control_period_s must be a positive multiple of the MJCF timestep")
        if not np.isfinite(max_delta_rad) or max_delta_rad <= 0:
            raise ValueError("max_delta_rad must be positive and finite")
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        if not np.isfinite(success_tolerance_rad) or success_tolerance_rad <= 0:
            raise ValueError("success_tolerance_rad must be positive and finite")
        if reward_mode not in {"sparse", "progress"}:
            raise ValueError("reward_mode must be 'sparse' or 'progress'")
        if task not in {"joint", "tcp"} or not np.isfinite(success_tolerance_m) or success_tolerance_m <= 0:
            raise ValueError("invalid task or TCP success tolerance")
        if not np.isfinite(reset_noise_rad) or not 0 <= reset_noise_rad <= 0.3:
            raise ValueError("reset_noise_rad must be in [0, 0.3]")
        goal = np.asarray(goal_rad, dtype=np.float64)
        if goal.shape != (7,) or not np.all(np.isfinite(goal)):
            raise ValueError("goal_rad must contain seven finite values")
        if np.any(goal < self.joint_limits[:, 0]) or np.any(goal > self.joint_limits[:, 1]):
            raise ValueError("goal_rad exceeds surrogate joint limits")

        self.physics_ticks = int(round(ticks))
        self.max_delta_rad = float(max_delta_rad)
        self.max_steps = max_steps
        self.goal_rad = goal
        self.success_tolerance_rad = float(success_tolerance_rad)
        self.reward_mode = reward_mode
        self.reset_noise_rad = float(reset_noise_rad)
        self.task = task
        self.success_tolerance_m = float(success_tolerance_m)
        self.model_kind = model_kind
        self.target_tcp_pos = self._tcp_at(goal)
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(7,), dtype=np.float32)
        state_low = np.concatenate((self.joint_limits[:, 0], np.full(7, -100.0))).astype(np.float32)
        state_high = np.concatenate((self.joint_limits[:, 1], np.full(7, 100.0))).astype(np.float32)
        self.observation_space = gym.spaces.Dict(
            {
                "state": gym.spaces.Box(state_low, state_high, dtype=np.float32),
                "tcp_pos": gym.spaces.Box(-10.0, 10.0, shape=(3,), dtype=np.float32),
                "target_tcp_pos": gym.spaces.Box(-10.0, 10.0, shape=(3,), dtype=np.float32),
            }
        )
        self._steps = 0
        self._finished = False
        self.reset()

    def _tcp_at(self, joints: np.ndarray) -> np.ndarray:
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self.qpos_ids] = joints
        self.data.ctrl[self.actuator_ids] = joints
        mujoco.mj_forward(self.model, self.data)
        return self.data.site_xpos[self.tcp_site_id].copy()

    def _distance(self) -> float:
        if self.task == "tcp":
            return float(np.linalg.norm(self.data.site_xpos[self.tcp_site_id] - self.target_tcp_pos))
        return float(np.linalg.norm(self.data.qpos[self.qpos_ids] - self.goal_rad))

    def _observation(self) -> dict[str, np.ndarray]:
        qpos = self.data.qpos[self.qpos_ids]
        qvel = self.data.qvel[self.qvel_ids]
        if not np.all(np.isfinite(qpos)) or not np.all(np.isfinite(qvel)):
            raise RuntimeError("MuJoCo joint state is nonfinite")
        return {
            "state": np.concatenate((qpos, qvel)).astype(np.float32),
            "tcp_pos": self.data.site_xpos[self.tcp_site_id].astype(np.float32).copy(),
            "target_tcp_pos": self.target_tcp_pos.astype(np.float32).copy(),
        }

    @staticmethod
    def _validate_action(action: np.ndarray, label: str) -> np.ndarray:
        value = np.asarray(action, dtype=np.float64)
        if value.shape != (7,) or not np.all(np.isfinite(value)):
            raise ValueError(f"{label} must contain seven finite values")
        if np.any(np.abs(value) > 1.0):
            raise ValueError(f"{label} must be within [-1, 1]")
        return value

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if options:
            raise ValueError("reset options are not supported by the surrogate")
        mujoco.mj_resetData(self.model, self.data)
        if self.reset_noise_rad:
            initial = self.np_random.uniform(-self.reset_noise_rad, self.reset_noise_rad, size=7)
            initial = np.clip(initial, self.joint_limits[:, 0], self.joint_limits[:, 1])
            self.data.qpos[self.qpos_ids] = initial
        self.data.ctrl[self.actuator_ids] = self.data.qpos[self.qpos_ids]
        mujoco.mj_forward(self.model, self.data)
        self._steps = 0
        self._finished = False
        return self._observation(), {"model_kind": self.model_kind, "task": self.task}

    def step(
        self,
        action: np.ndarray,
        *,
        intervention_active: bool = False,
        human_action: np.ndarray | None = None,
    ):
        if self._finished:
            raise RuntimeError("episode ended; call reset before step")
        policy = self._validate_action(action, "policy action")
        if intervention_active:
            if human_action is None:
                raise ValueError("active intervention requires human_action")
            requested = self._validate_action(human_action, "human action")
            source = "human"
        else:
            if human_action is not None:
                raise ValueError("human_action requires intervention_active=True")
            requested = policy
            source = "policy"

        current = self.data.qpos[self.qpos_ids].copy()
        distance_before = self._distance()
        target = np.clip(
            current + requested * self.max_delta_rad,
            self.joint_limits[:, 0],
            self.joint_limits[:, 1],
        )
        executed = (target - current) / self.max_delta_rad
        self.data.ctrl[self.actuator_ids] = target
        for _ in range(self.physics_ticks):
            mujoco.mj_step(self.model, self.data)

        obs = self._observation()
        self._steps += 1
        joint_error = float(np.max(np.abs(obs["state"][:7] - self.goal_rad)))
        tcp_error = float(np.linalg.norm(obs["tcp_pos"] - self.target_tcp_pos))
        terminated = (tcp_error <= self.success_tolerance_m if self.task == "tcp" else joint_error <= self.success_tolerance_rad)
        truncated = self._steps >= self.max_steps and not terminated
        self._finished = terminated or truncated
        if self.reward_mode == "progress":
            distance_after = self._distance()
            reward = 10.0 * (distance_before - distance_after) - 0.01 + float(terminated)
        else:
            reward = float(terminated)
        info = {
            "action_source": source,
            "intervention_active": intervention_active,
            "policy_action": policy.astype(np.float32),
            "human_action": requested.astype(np.float32) if intervention_active else None,
            "executed_action": executed.astype(np.float32),
            "commanded_joint_target_rad": target.astype(np.float32),
            "goal_error_rad": joint_error,
            "tcp_error_m": tcp_error,
            "model_kind": self.model_kind,
            "task": self.task,
        }
        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        self.data = None
        self.model = None
