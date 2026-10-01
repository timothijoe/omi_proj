"""Explicitly gated Tianji Marvin SDK boundary.

Construction and import do not connect to a controller. Motion requires
site-provided limits and ``motion_authorized=True`` plus an explicit arm call.
This adapter has only fake-SDK tests; it has not been commissioned on hardware.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


@dataclass(frozen=True)
class TianjiConfig:
    robot_ip: str
    arm: str
    joint_limits_deg: tuple[tuple[float, float], ...]
    max_step_deg: float
    vel_ratio: int
    acc_ratio: int
    motion_authorized: bool = False
    feedback_timeout_s: float = 0.5
    sdk_root: Path | None = None

    def __post_init__(self):
        limits = np.asarray(self.joint_limits_deg, dtype=float)
        if self.arm not in {"A", "B"} or not self.robot_ip:
            raise ValueError("arm must be A or B and robot_ip must be provided")
        if limits.shape != (7, 2) or not np.all(np.isfinite(limits)) or not np.all(limits[:, 0] < limits[:, 1]):
            raise ValueError("joint_limits_deg must be seven finite low/high pairs")
        if not math.isfinite(self.max_step_deg) or not 0 < self.max_step_deg <= 1:
            raise ValueError("max_step_deg must be in (0, 1]")
        if not 1 <= self.vel_ratio <= 100 or not 1 <= self.acc_ratio <= 100:
            raise ValueError("vel_ratio and acc_ratio must be in [1, 100]")
        if not math.isfinite(self.feedback_timeout_s) or self.feedback_timeout_s <= 0:
            raise ValueError("feedback_timeout_s must be positive")


@dataclass(frozen=True)
class TianjiArmState:
    joint_position_rad: np.ndarray
    frame_serial: int
    controller_state: int
    error_code: int
    received_monotonic_s: float


class TianjiSdkArm:
    """One selected arm using the vendor concise SDK.

    SDK objects may be injected for no-hardware tests. ``connect()`` only
    connects and reads; it never switches mode or sends a motion target.
    """

    def __init__(
        self,
        config: TianjiConfig,
        *,
        sdk_factory: Callable[[], Any] | None = None,
        dcss_factory: Callable[[], Any] | None = None,
    ):
        self.config = config
        self._sdk_factory = sdk_factory
        self._dcss_factory = dcss_factory
        self._sdk = None
        self._dcss = None
        self._armed = False
        self._faulted = False
        self._last_frame = None
        self._last_frame_change_s = None
        self._feedback_advanced = False

    def _fault(self, message: str) -> None:
        self._faulted = True
        if self._armed:
            try:
                self.stop()
            except Exception as exc:
                raise RuntimeError(f"{message}; software stop failed: {exc}") from exc
        raise RuntimeError(message)

    def _factories(self):
        if self._sdk_factory is not None and self._dcss_factory is not None:
            return self._sdk_factory, self._dcss_factory
        if self.config.sdk_root is None:
            raise RuntimeError("sdk_root is required unless SDK factories are injected")
        root = str(self.config.sdk_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        from SDK_PYTHON.fx_robot import Concise_Marvin_Robot, DCSS

        return Concise_Marvin_Robot, DCSS

    def connect(self) -> TianjiArmState:
        if self._sdk is not None:
            raise RuntimeError("already connected")
        sdk_factory, dcss_factory = self._factories()
        sdk = sdk_factory()
        if sdk.connect(self.config.robot_ip) is not True:
            raise RuntimeError("Tianji SDK connect failed")
        self._sdk = sdk
        self._dcss = dcss_factory()
        try:
            return self.read_state()
        except Exception:
            self.close()
            raise

    def read_state(self) -> TianjiArmState:
        if self._sdk is None:
            raise RuntimeError("not connected")
        data = self._sdk.subscribe(self._dcss)
        index = 0 if self.config.arm == "A" else 1
        try:
            output = data["outputs"][index]
            status = data["states"][index]
            joints_deg = np.asarray(output["fb_joint_pos"], dtype=float)
            frame = int(output["frame_serial"])
            controller_state = int(status["cur_state"])
            error = int(status["err_code"])
        except (TypeError, KeyError, IndexError, ValueError) as exc:
            self._fault("invalid Tianji feedback")
        if joints_deg.shape != (7,) or not np.all(np.isfinite(joints_deg)) or frame <= 0:
            self._fault("invalid Tianji joint feedback or frame")
        now = time.monotonic()
        if frame != self._last_frame:
            if self._last_frame is not None:
                self._feedback_advanced = True
            self._last_frame = frame
            self._last_frame_change_s = now
        elif now - self._last_frame_change_s > self.config.feedback_timeout_s:
            self._fault("Tianji feedback frame is stale")
        if error != 0:
            self._fault(f"Tianji controller error: {error}")
        return TianjiArmState(np.deg2rad(joints_deg), frame, controller_state, error, now)

    def arm_position_mode(self) -> TianjiArmState:
        if not self.config.motion_authorized:
            raise PermissionError("motion is disabled in TianjiConfig")
        if self._faulted or self._sdk is None:
            raise RuntimeError("cannot arm disconnected or faulted SDK")
        state = self.read_state()
        if not self._feedback_advanced:
            raise RuntimeError("feedback must advance before arming")
        if self._sdk.set_position_state(
            self.config.arm, self.config.vel_ratio, self.config.acc_ratio
        ) is not True:
            self._fault("Tianji rejected position mode")
        deadline = time.monotonic() + self.config.feedback_timeout_s
        while time.monotonic() < deadline:
            state = self.read_state()
            if state.controller_state == 1:
                self._armed = True
                return state
            time.sleep(0.01)
        self._fault("Tianji did not enter position mode")

    def send_joint_target_rad(self, target_rad: np.ndarray) -> TianjiArmState:
        if not self._armed or self._faulted:
            raise RuntimeError("Tianji arm is not armed or is faulted")
        target = np.asarray(target_rad, dtype=float)
        if target.shape != (7,) or not np.all(np.isfinite(target)):
            raise ValueError("target must be seven finite radians")
        target_deg = np.rad2deg(target)
        limits = np.asarray(self.config.joint_limits_deg)
        if np.any(target_deg < limits[:, 0]) or np.any(target_deg > limits[:, 1]):
            raise ValueError("target exceeds site-approved joint limits")
        state = self.read_state()
        if state.controller_state != 1:
            self._fault("Tianji left position mode")
        current_deg = np.rad2deg(state.joint_position_rad)
        if np.any(np.abs(target_deg - current_deg) > self.config.max_step_deg + 1e-9):
            raise ValueError("target exceeds site-approved single-step limit")
        try:
            accepted = self._sdk.set_joint_position_cmd(self.config.arm, target_deg.tolist())
        except Exception as exc:
            self._fault(f"Tianji joint command failed: {exc}")
        if accepted is not True:
            self._fault("Tianji rejected joint target")
        return state

    def stop(self) -> None:
        if self._sdk is None:
            return
        self._faulted = True
        try:
            self._sdk.soft_stop(self.config.arm)
        finally:
            try:
                if self._sdk.disable(self.config.arm) is not True:
                    raise RuntimeError("Tianji disable was not acknowledged")
            finally:
                self._armed = False

    def close(self) -> None:
        if self._sdk is None:
            return
        try:
            if self._armed:
                if self._sdk.disable(self.config.arm) is not True:
                    raise RuntimeError("Tianji disable was not acknowledged")
        finally:
            self._armed = False
            self._sdk.release_robot()
            self._sdk = None
