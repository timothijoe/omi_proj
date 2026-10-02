"""ROS 2 message ingestion for the read-only insertion observation builder.

Importing this module does not initialize ROS, connect to hardware, or publish
commands. ROS imports used by the live node are intentionally lazy.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import numpy as np

from .observation import ObservationConfig, TianjiInsertionObservationBuilder


@dataclass(frozen=True)
class TianjiTopicNames:
    joint_feedback: str = "/tj/info/joint_feedback"
    gripper_state: str = "/dm_gripper/joint_states"
    external_rgb: str = "/camera/camera/color/image_raw"
    wrist_rgb: str = "/tj/dm_sensor/camera/color"
    tactile_a_raw: str = "/tj/dm_sensor/a_raw"
    tactile_b_raw: str = "/tj/dm_sensor/b_raw"
    tactile_a_depth: str = "/tj/dm_sensor/a_depth"
    tactile_b_depth: str = "/tj/dm_sensor/b_depth"
    tactile_a_force: str = "/tj/dm_sensor/a_force"
    tactile_b_force: str = "/tj/dm_sensor/b_force"

    def sensor_for_topic(self) -> dict[str, str]:
        return {
            self.joint_feedback: "joint",
            self.gripper_state: "gripper",
            self.external_rgb: "external_rgb",
            self.wrist_rgb: "wrist_rgb",
            self.tactile_a_raw: "tactile_a_raw",
            self.tactile_b_raw: "tactile_b_raw",
            self.tactile_a_depth: "tactile_a_depth",
            self.tactile_b_depth: "tactile_b_depth",
            self.tactile_a_force: "tactile_a_force",
            self.tactile_b_force: "tactile_b_force",
        }


def message_timestamp_ns(message: Any, fallback_ns: int) -> int:
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is not None:
        value = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
        if value > 0:
            return value
    if fallback_ns <= 0:
        raise ValueError("fallback timestamp must be positive")
    return fallback_ns


def decode_image_message(message: Any) -> np.ndarray:
    height = int(message.height)
    width = int(message.width)
    step = int(message.step)
    encoding = str(message.encoding).lower()
    if height < 1 or width < 1 or step < 1:
        raise ValueError("image dimensions and step must be positive")
    raw = memoryview(message.data)
    if len(raw) != height * step:
        raise ValueError("image payload size does not match height * step")

    if encoding in {"rgb8", "bgr8"}:
        if step < width * 3:
            raise ValueError("RGB image step is too small")
        array = np.frombuffer(raw, dtype=np.uint8).reshape(height, step)[:, : width * 3]
        array = array.reshape(height, width, 3)
        if encoding == "bgr8":
            array = array[..., ::-1]
        return np.ascontiguousarray(array)
    if encoding == "mono8":
        if step < width:
            raise ValueError("mono8 image step is too small")
        return np.frombuffer(raw, dtype=np.uint8).reshape(height, step)[:, :width].copy()
    if encoding in {"16uc1", "mono16"}:
        dtype = np.dtype(">u2" if bool(message.is_bigendian) else "<u2")
    elif encoding in {"32fc1", "32fc2"}:
        dtype = np.dtype(">f4" if bool(message.is_bigendian) else "<f4")
    else:
        raise ValueError(f"unsupported image encoding {message.encoding!r}")
    channels = 2 if encoding == "32fc2" else 1
    if step % dtype.itemsize or step < width * channels * dtype.itemsize:
        raise ValueError("depth image step is incompatible with its encoding")
    row_values = step // dtype.itemsize
    array = np.frombuffer(raw, dtype=dtype).reshape(height, row_values)[:, :width * channels]
    if channels == 2:
        array = array.reshape(height, width, channels)
    return np.asarray(array, dtype=dtype.newbyteorder("=")).copy()


def joint_feedback_value(message: Any) -> dict[str, np.ndarray]:
    position = np.asarray(message.arm_positions, dtype=np.float32)
    velocity = np.asarray(message.arm_velocities, dtype=np.float32)
    effort = np.asarray(message.arm_efforts, dtype=np.float32)
    if position.shape != (14,) or velocity.shape != (14,) or effort.shape != (14,):
        raise ValueError("joint feedback must contain left and right seven-joint arrays")
    if not np.all(np.isfinite(position)) or not np.all(np.isfinite(velocity)) or not np.all(np.isfinite(effort)):
        raise ValueError("joint feedback contains non-finite values")
    return {"position": position[:7], "velocity": velocity[:7], "effort": effort[:7]}


def gripper_value(message: Any) -> float:
    position = np.asarray(message.position, dtype=float)
    if position.size < 1 or not np.isfinite(position[0]):
        raise ValueError("gripper state has no finite position")
    return float(position[0])


def wrench_value(message: Any) -> np.ndarray:
    wrench = message.wrench
    value = np.asarray(
        [
            wrench.force.x,
            wrench.force.y,
            wrench.force.z,
            wrench.torque.x,
            wrench.torque.y,
            wrench.torque.z,
        ],
        dtype=np.float32,
    )
    if not np.all(np.isfinite(value)):
        raise ValueError("tactile wrench contains non-finite values")
    return value


class RosTopicIngestor:
    """Convert ROS-shaped messages and feed the pure observation builder."""

    def __init__(
        self,
        builder: TianjiInsertionObservationBuilder,
        topics: TianjiTopicNames | None = None,
    ) -> None:
        self.builder = builder
        self.topics = topics or TianjiTopicNames()
        self._sensor_by_topic = self.topics.sensor_for_topic()

    @property
    def subscribed_topics(self) -> tuple[str, ...]:
        return tuple(self._sensor_by_topic)

    def ingest(self, topic: str, message: Any, *, received_timestamp_ns: int | None = None) -> None:
        try:
            sensor = self._sensor_by_topic[topic]
        except KeyError as exc:
            raise KeyError(f"topic {topic!r} is not configured") from exc
        received = time.time_ns() if received_timestamp_ns is None else received_timestamp_ns
        source = message_timestamp_ns(message, received)
        if sensor == "joint":
            value = joint_feedback_value(message)
        elif sensor == "gripper":
            value = gripper_value(message)
        elif sensor.endswith("_force"):
            value = wrench_value(message)
        else:
            value = decode_image_message(message)
        self.builder.push(sensor, value, source_timestamp_ns=source, received_timestamp_ns=received)


class TianjiRosObservationNode:
    """Own a read-only rclpy node and subscriptions for all observation topics."""

    def __init__(
        self,
        config: ObservationConfig | None = None,
        topics: TianjiTopicNames | None = None,
        *,
        node_name: str = "omi_tianji_observation",
    ) -> None:
        try:
            import rclpy
            from geometry_msgs.msg import WrenchStamped
            from marvin_msgs.msg import Jointfeedback
            from rclpy.qos import qos_profile_sensor_data
            from sensor_msgs.msg import Image, JointState
        except ImportError as exc:
            raise RuntimeError(
                "ROS 2 Python packages and marvin_msgs must be sourced before creating the observation node"
            ) from exc

        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_rclpy = True
        else:
            self._owns_rclpy = False
        self._rclpy = rclpy
        self.node = rclpy.create_node(node_name)
        self.builder = TianjiInsertionObservationBuilder(config)
        self.ingestor = RosTopicIngestor(self.builder, topics)
        names = self.ingestor.topics
        topic_types = {
            names.joint_feedback: Jointfeedback,
            names.gripper_state: JointState,
            names.external_rgb: Image,
            names.wrist_rgb: Image,
            names.tactile_a_raw: Image,
            names.tactile_b_raw: Image,
            names.tactile_a_depth: Image,
            names.tactile_b_depth: Image,
            names.tactile_a_force: WrenchStamped,
            names.tactile_b_force: WrenchStamped,
        }
        self._subscriptions = []
        for topic, message_type in topic_types.items():
            callback = lambda message, topic=topic: self.ingestor.ingest(
                topic, message, received_timestamp_ns=self.node.get_clock().now().nanoseconds
            )
            self._subscriptions.append(
                self.node.create_subscription(message_type, topic, callback, qos_profile_sensor_data)
            )

    def spin_once(self, timeout_s: float = 0.1) -> None:
        self._rclpy.spin_once(self.node, timeout_sec=timeout_s)

    def now_ns(self) -> int:
        return self.node.get_clock().now().nanoseconds

    def capture_grasp_baseline(self) -> None:
        self.builder.capture_grasp_baseline(self.now_ns())

    def latest_observation(self) -> dict[str, np.ndarray]:
        return self.builder.build(self.now_ns())

    def latest_torch_observation(self, *, device: str = "cpu"):
        """Return a batched network input without coupling the ROS layer to Torch."""

        from .tensor_adapter import observation_to_torch

        return observation_to_torch(self.latest_observation(), device=device)

    def close(self) -> None:
        self.node.destroy_node()
        if self._owns_rclpy and self._rclpy.ok():
            self._rclpy.shutdown()
