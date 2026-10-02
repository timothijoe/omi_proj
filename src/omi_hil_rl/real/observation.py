"""Time-aligned observations for tactile insertion on a real Tianji arm.

This module is independent of ROS so timestamp selection, stale-data handling,
baseline subtraction, and network input shapes can be tested without hardware.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import threading
from typing import Any

import gymnasium as gym
import numpy as np


DEFAULT_SENSOR_GROUPS = (
    "joint",
    "gripper",
    "external_rgb",
    "wrist_rgb",
    "tactile_a_raw",
    "tactile_b_raw",
    "tactile_a_depth",
    "tactile_b_depth",
    "tactile_a_force",
    "tactile_b_force",
)


class ObservationNotReady(RuntimeError):
    """Raised when a required sample or grasp baseline is unavailable."""


@dataclass(frozen=True)
class SquareRoi:
    """Resolution-independent square camera crop."""

    center_x: float
    center_y: float
    side_of_min_dimension: float

    def __post_init__(self) -> None:
        for name, value in (
            ("center_x", self.center_x),
            ("center_y", self.center_y),
            ("side_of_min_dimension", self.side_of_min_dimension),
        ):
            if not np.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.center_x <= 1.0 or not 0.0 <= self.center_y <= 1.0:
            raise ValueError("ROI center coordinates must be in [0, 1]")
        if not 0.0 < self.side_of_min_dimension <= 1.0:
            raise ValueError("ROI side must be in (0, 1]")


@dataclass(frozen=True)
class TimedSample:
    source_timestamp_ns: int
    received_timestamp_ns: int
    value: Any


class TimestampedBuffer:
    """Small thread-safe buffer queried by acquisition timestamp.

    ROS callbacks may arrive slightly out of order. Samples are therefore kept
    sorted by source timestamp instead of relying on callback order.
    """

    def __init__(self, capacity: int = 512) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._timestamps: list[int] = []
        self._samples: list[TimedSample] = []
        self._lock = threading.RLock()

    def append(self, sample: TimedSample) -> None:
        if sample.source_timestamp_ns <= 0 or sample.received_timestamp_ns <= 0:
            raise ValueError("timestamps must be positive")
        with self._lock:
            index = bisect_right(self._timestamps, sample.source_timestamp_ns)
            self._timestamps.insert(index, sample.source_timestamp_ns)
            self._samples.insert(index, sample)
            overflow = len(self._samples) - self.capacity
            if overflow > 0:
                del self._timestamps[:overflow]
                del self._samples[:overflow]

    def latest_at(self, timestamp_ns: int) -> TimedSample | None:
        with self._lock:
            index = bisect_right(self._timestamps, timestamp_ns) - 1
            return None if index < 0 else self._samples[index]

    def between(self, start_timestamp_ns: int, end_timestamp_ns: int) -> list[TimedSample]:
        if start_timestamp_ns > end_timestamp_ns:
            raise ValueError("start timestamp must not exceed end timestamp")
        with self._lock:
            start = bisect_right(self._timestamps, start_timestamp_ns - 1)
            end = bisect_right(self._timestamps, end_timestamp_ns)
            return list(self._samples[start:end])

    @property
    def oldest_timestamp_ns(self) -> int | None:
        with self._lock:
            return self._timestamps[0] if self._timestamps else None

    @property
    def latest_timestamp_ns(self) -> int | None:
        with self._lock:
            return self._timestamps[-1] if self._timestamps else None


@dataclass(frozen=True)
class ObservationConfig:
    external_rgb_shape: tuple[int, int] = (128, 128)
    wrist_rgb_shape: tuple[int, int] = (128, 128)
    external_rgb_roi: SquareRoi = SquareRoi(0.507, 0.426, 0.40)
    wrist_rgb_roi: SquareRoi = SquareRoi(0.500, 0.704, 0.36)
    tactile_shape: tuple[int, int] = (64, 64)
    max_age_s: float = 0.25
    baseline_window_s: float = 0.5
    required_sensors: tuple[str, ...] = DEFAULT_SENSOR_GROUPS
    require_grasp_baseline: bool = True
    buffer_capacity: int = 512

    def __post_init__(self) -> None:
        for name, shape in (
            ("external_rgb_shape", self.external_rgb_shape),
            ("wrist_rgb_shape", self.wrist_rgb_shape),
            ("tactile_shape", self.tactile_shape),
        ):
            if len(shape) != 2 or any(not isinstance(x, int) or x < 1 for x in shape):
                raise ValueError(f"{name} must be two positive integers")
        if not np.isfinite(self.max_age_s) or self.max_age_s <= 0:
            raise ValueError("max_age_s must be positive and finite")
        if not np.isfinite(self.baseline_window_s) or self.baseline_window_s < 0:
            raise ValueError("baseline_window_s must be nonnegative and finite")
        unknown = set(self.required_sensors) - set(DEFAULT_SENSOR_GROUPS)
        if unknown:
            raise ValueError(f"unknown required sensors: {sorted(unknown)}")


def _resize_nearest(array: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    value = np.asarray(array)
    if value.ndim not in (2, 3) or value.shape[0] < 1 or value.shape[1] < 1:
        raise ValueError("image must be a non-empty HxW or HxWxC array")
    rows = np.rint(np.linspace(0, value.shape[0] - 1, shape[0])).astype(int)
    cols = np.rint(np.linspace(0, value.shape[1] - 1, shape[1])).astype(int)
    return value[rows[:, None], cols[None, :]]


def _crop_square_resize_nearest(
    array: np.ndarray,
    roi: SquareRoi,
    shape: tuple[int, int],
) -> tuple[np.ndarray, tuple[int, int, int]]:
    """Crop a clamped square ROI, resize it, and return (left, top, side)."""

    value = np.asarray(array)
    if value.ndim != 3 or value.shape[2] != 3 or value.shape[0] < 1 or value.shape[1] < 1:
        raise ValueError("RGB image must be a non-empty HxWx3 array")
    height, width = value.shape[:2]
    side = max(1, int(round(min(width, height) * roi.side_of_min_dimension)))
    center_x = int(round(width * roi.center_x))
    center_y = int(round(height * roi.center_y))
    left = max(0, min(width - side, center_x - side // 2))
    top = max(0, min(height - side, center_y - side // 2))
    crop = value[top : top + side, left : left + side]
    return _resize_nearest(crop, shape), (left, top, side)


class TianjiInsertionObservationBuilder:
    """Build a fixed-shape tactile-insertion observation at a decision time."""

    def __init__(self, config: ObservationConfig | None = None) -> None:
        self.config = config or ObservationConfig()
        self.buffers = {
            name: TimestampedBuffer(self.config.buffer_capacity)
            for name in DEFAULT_SENSOR_GROUPS
        }
        self._baseline_wrench: np.ndarray | None = None
        self._baseline_depth: np.ndarray | None = None
        self._baseline_timestamp_ns: int | None = None
        self._external_rgb_roi = self.config.external_rgb_roi

        external_h, external_w = self.config.external_rgb_shape
        wrist_h, wrist_w = self.config.wrist_rgb_shape
        tactile_h, tactile_w = self.config.tactile_shape
        age_high = np.full(len(DEFAULT_SENSOR_GROUPS), np.finfo(np.float32).max)
        self.observation_space = gym.spaces.Dict(
            {
                "state": gym.spaces.Box(-np.inf, np.inf, shape=(22,), dtype=np.float32),
                "wrench_delta": gym.spaces.Box(-np.inf, np.inf, shape=(12,), dtype=np.float32),
                "external_rgb": gym.spaces.Box(0, 255, shape=(external_h, external_w, 3), dtype=np.uint8),
                "external_rgb_roi_offset_px": gym.spaces.Box(
                    -np.inf, np.inf, shape=(2,), dtype=np.float32
                ),
                "wrist_rgb": gym.spaces.Box(0, 255, shape=(wrist_h, wrist_w, 3), dtype=np.uint8),
                "tactile_raw": gym.spaces.Box(0, 255, shape=(tactile_h, tactile_w, 2), dtype=np.uint8),
                "tactile_depth_delta": gym.spaces.Box(-np.inf, np.inf, shape=(tactile_h, tactile_w, 2), dtype=np.float32),
                "sensor_age_s": gym.spaces.Box(np.zeros_like(age_high), age_high, dtype=np.float32),
                "sensor_valid": gym.spaces.MultiBinary(len(DEFAULT_SENSOR_GROUPS)),
            }
        )

    def set_external_rgb_roi_center(self, center_x: float, center_y: float) -> None:
        """Move the head-camera ROI; its per-frame pixel offset is recorded.

        Coordinates are fractions of source width/height.  This is intended
        for a future object tracker; the wrist ROI intentionally stays fixed.
        """

        self._external_rgb_roi = SquareRoi(
            center_x,
            center_y,
            self.config.external_rgb_roi.side_of_min_dimension,
        )

    def push(
        self,
        sensor: str,
        value: Any,
        *,
        source_timestamp_ns: int,
        received_timestamp_ns: int | None = None,
    ) -> None:
        if sensor not in self.buffers:
            raise KeyError(f"unknown sensor {sensor!r}")
        received = source_timestamp_ns if received_timestamp_ns is None else received_timestamp_ns
        self.buffers[sensor].append(TimedSample(source_timestamp_ns, received, value))

    def _samples_at(self, timestamp_ns: int) -> tuple[dict[str, TimedSample], np.ndarray, np.ndarray]:
        samples: dict[str, TimedSample] = {}
        ages = np.full(len(DEFAULT_SENSOR_GROUPS), np.inf, dtype=np.float32)
        valid = np.zeros(len(DEFAULT_SENSOR_GROUPS), dtype=np.int8)
        max_age_ns = int(self.config.max_age_s * 1e9)
        errors = []
        for index, name in enumerate(DEFAULT_SENSOR_GROUPS):
            sample = self.buffers[name].latest_at(timestamp_ns)
            if sample is None:
                if name in self.config.required_sensors:
                    errors.append(f"{name}:missing")
                continue
            age_ns = timestamp_ns - sample.source_timestamp_ns
            if age_ns < 0:
                raise RuntimeError("buffer selected a future sample")
            ages[index] = age_ns / 1e9
            if age_ns <= max_age_ns:
                samples[name] = sample
                valid[index] = 1
            elif name in self.config.required_sensors:
                errors.append(f"{name}:stale({age_ns / 1e9:.3f}s)")
        if errors:
            raise ObservationNotReady(", ".join(errors))
        return samples, ages, valid

    @staticmethod
    def _required_value(samples: dict[str, TimedSample], name: str) -> Any:
        try:
            return samples[name].value
        except KeyError as exc:
            raise ObservationNotReady(f"{name} is unavailable") from exc

    def capture_grasp_baseline(self, timestamp_ns: int) -> None:
        samples, _, _ = self._samples_at(timestamp_ns)
        # Requiring current samples first gives a clear stale/missing error even
        # though the baseline itself is averaged over a short history window.
        for name in ("tactile_a_force", "tactile_b_force", "tactile_a_depth", "tactile_b_depth"):
            self._required_value(samples, name)
        start_ns = timestamp_ns - int(self.config.baseline_window_s * 1e9)

        def values(name: str) -> list[Any]:
            history = self.buffers[name].between(start_ns, timestamp_ns)
            if not history:
                raise ObservationNotReady(f"{name} has no samples in the baseline window")
            return [item.value for item in history]

        wrench_a_values = [np.asarray(value, dtype=np.float32) for value in values("tactile_a_force")]
        wrench_b_values = [np.asarray(value, dtype=np.float32) for value in values("tactile_b_force")]
        if any(value.shape != (6,) for value in wrench_a_values + wrench_b_values):
            raise ValueError("each tactile wrench must contain six values")
        wrench_a = np.mean(np.stack(wrench_a_values), axis=0)
        wrench_b = np.mean(np.stack(wrench_b_values), axis=0)
        depth_a = np.mean(
            np.stack([_resize_nearest(np.asarray(value, dtype=np.float32), self.config.tactile_shape) for value in values("tactile_a_depth")]),
            axis=0,
        )
        depth_b = np.mean(
            np.stack([_resize_nearest(np.asarray(value, dtype=np.float32), self.config.tactile_shape) for value in values("tactile_b_depth")]),
            axis=0,
        )
        depth = np.stack((depth_a, depth_b), axis=-1)
        if not np.all(np.isfinite(depth)) or not np.all(np.isfinite(wrench_a)) or not np.all(np.isfinite(wrench_b)):
            raise ValueError("grasp baseline contains non-finite values")
        self._baseline_wrench = np.concatenate((wrench_a, wrench_b))
        self._baseline_depth = depth.astype(np.float32)
        self._baseline_timestamp_ns = timestamp_ns

    @property
    def baseline_timestamp_ns(self) -> int | None:
        return self._baseline_timestamp_ns

    def validate_sensor_set(self, timestamp_ns: int) -> None:
        """Raise ``ObservationNotReady`` unless required inputs are fresh."""

        self._samples_at(timestamp_ns)

    def build(self, timestamp_ns: int) -> dict[str, np.ndarray]:
        samples, ages, valid = self._samples_at(timestamp_ns)
        if self.config.require_grasp_baseline and (
            self._baseline_wrench is None or self._baseline_depth is None
        ):
            raise ObservationNotReady("grasp baseline has not been captured")

        joint = self._required_value(samples, "joint")
        qpos = np.asarray(joint["position"], dtype=np.float32)
        qvel = np.asarray(joint["velocity"], dtype=np.float32)
        effort = np.asarray(joint["effort"], dtype=np.float32)
        if qpos.shape != (7,) or qvel.shape != (7,) or effort.shape != (7,):
            raise ValueError("A-arm joint state must contain seven positions, velocities, and efforts")
        gripper = float(self._required_value(samples, "gripper"))
        state = np.concatenate((qpos, qvel, effort, np.asarray([gripper], dtype=np.float32)))

        wrench = np.concatenate(
            (
                np.asarray(self._required_value(samples, "tactile_a_force"), dtype=np.float32),
                np.asarray(self._required_value(samples, "tactile_b_force"), dtype=np.float32),
            )
        )
        if wrench.shape != (12,) or not np.all(np.isfinite(wrench)):
            raise ValueError("tactile wrench must contain twelve finite values")

        raw = np.stack(
            (
                _resize_nearest(np.asarray(self._required_value(samples, "tactile_a_raw")), self.config.tactile_shape),
                _resize_nearest(np.asarray(self._required_value(samples, "tactile_b_raw")), self.config.tactile_shape),
            ),
            axis=-1,
        ).astype(np.uint8)
        depth = np.stack(
            (
                _resize_nearest(np.asarray(self._required_value(samples, "tactile_a_depth"), dtype=np.float32), self.config.tactile_shape),
                _resize_nearest(np.asarray(self._required_value(samples, "tactile_b_depth"), dtype=np.float32), self.config.tactile_shape),
            ),
            axis=-1,
        )
        if not np.all(np.isfinite(depth)):
            raise ValueError("tactile depth contains non-finite values")

        external_source = np.asarray(self._required_value(samples, "external_rgb"))
        wrist_source = np.asarray(self._required_value(samples, "wrist_rgb"))
        external, (external_left, external_top, external_side) = _crop_square_resize_nearest(
            external_source, self._external_rgb_roi, self.config.external_rgb_shape
        )
        wrist, _ = _crop_square_resize_nearest(
            wrist_source, self.config.wrist_rgb_roi, self.config.wrist_rgb_shape
        )
        external = external.astype(np.uint8)
        wrist = wrist.astype(np.uint8)
        if external.shape[-1:] != (3,) or wrist.shape[-1:] != (3,):
            raise ValueError("RGB observations must have three channels")
        external_roi_offset_px = np.asarray(
            [
                external_left + external_side / 2.0 - external_source.shape[1] / 2.0,
                external_top + external_side / 2.0 - external_source.shape[0] / 2.0,
            ],
            dtype=np.float32,
        )

        baseline_wrench = np.zeros(12, dtype=np.float32) if self._baseline_wrench is None else self._baseline_wrench
        baseline_depth = np.zeros_like(depth, dtype=np.float32) if self._baseline_depth is None else self._baseline_depth
        observation = {
            "state": state.astype(np.float32),
            "wrench_delta": (wrench - baseline_wrench).astype(np.float32),
            "external_rgb": external,
            "external_rgb_roi_offset_px": external_roi_offset_px,
            "wrist_rgb": wrist,
            "tactile_raw": raw,
            "tactile_depth_delta": (depth - baseline_depth).astype(np.float32),
            "sensor_age_s": ages,
            "sensor_valid": valid,
        }
        if not self.observation_space.contains(observation):
            raise ValueError("assembled observation is outside the declared observation space")
        return observation

    def common_time_range_ns(self) -> tuple[int, int]:
        names = self.config.required_sensors
        starts = [self.buffers[name].oldest_timestamp_ns for name in names]
        ends = [self.buffers[name].latest_timestamp_ns for name in names]
        if any(value is None for value in starts + ends):
            raise ObservationNotReady("one or more required sensor buffers are empty")
        start = max(int(value) for value in starts if value is not None)
        end = min(int(value) for value in ends if value is not None)
        if start > end:
            raise ObservationNotReady("required sensors have no overlapping time range")
        return start, end
