"""Explicit HIL observation, action and operator-event contracts."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class HILConfig:
    hz: float = 10.
    episode_seconds: float = 15.
    translation_step_m: float = .001 / math.sqrt(3.)
    rotation_step_rad: float = math.pi / 180 / math.sqrt(3.)
    start_button: int = 315
    success_button: int = 307
    keep_button: int = 304
    discard_button: int = 305
    review: str = "manual"
    transport: str = "fake"
    eef_reference: str = "raw"
    wrist_camera: str = "optional"
    sdk_convention: str = "sdk-x-forward-z-left"

    def __post_init__(self):
        for value in (self.hz, self.episode_seconds, self.translation_step_m, self.rotation_step_rad):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("rates, duration and action scales must be positive and finite")
        if self.hz != 10.:
            raise ValueError("the current history observation contract requires 10 Hz")
        buttons = (self.start_button, self.success_button, self.keep_button, self.discard_button)
        if any(type(v) is not int or v < 0 or v == 311 for v in buttons) or len(set(buttons)) != 4:
            raise ValueError("four distinct event buttons, separate from RB, required")
        if self.review not in ("manual", "auto") or self.transport not in ("fake", "ros"):
            raise ValueError("unknown review or transport mode")
        if self.wrist_camera not in ("optional", "required", "off"):
            raise ValueError("unknown wrist camera mode")
        if self.sdk_convention not in ("sdk-base-aligned", "sdk-x-forward-z-left"):
            raise ValueError("SDK ABC conversion required")
        if self.eef_reference not in ("raw", "bag-baseline-v1"):
            raise ValueError("unknown EEF reference")

    @property
    def action_scale(self):
        return np.array([self.translation_step_m] * 3 + [self.rotation_step_rad] * 3, np.float32)

    def physical_action(self, normalized):
        action = np.asarray(normalized, np.float32)
        if action.shape != (6,) or not np.isfinite(action).all() or np.any(np.abs(action) > 1.000001):
            raise ValueError("expected finite normalized six-dimensional action")
        return action * self.action_scale

    def normalized_action(self, physical):
        action = np.asarray(physical, np.float32) / self.action_scale
        if action.shape != (6,) or not np.isfinite(action).all() or np.any(np.abs(action) > 1.000001):
            raise ValueError("adopted physical command outside action contract")
        return np.clip(action, -1, 1)

    def replay_contract(self):
        def spec(shape, dtype="float32", low=-1e30, high=1e30):
            return dict(shape=shape, dtype=dtype, low=low, high=high)
        return dict(schema_version=1,
            observation_contract="hil-nojoint-current9stack-v1-" + self.transport,
            action_contract="hil-left-base-normalized-component-delta-v1",
            action_semantics="accepted_command", reward_contract="human-success-0-1-timeout-bootstrap-v1",
            observations=dict(rgb=spec([10, 3, 128, 128], "uint8", 0, 255),
                wrist_rgb=spec([10, 3, 128, 128], "uint8", 0, 255),
                tactile=spec([10, 10, 16, 24]), state=spec([10, 14]),
                camera_mask=spec([10, 2], low=0, high=1), history_mask=spec([10], "uint8", 0, 1)),
            action=spec([6], low=-1, high=1), physical_action_scale=self.action_scale.tolist(),
            hz=self.hz, episode_seconds=self.episode_seconds, eef_reference=self.eef_reference,
            no_joints=True, no_gripper=True, config=asdict(self))


def load_config(path):
    return HILConfig(**json.loads(Path(path).read_text()))
