"""Validate a ROS 2 bag against the read-only insertion observation contract."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .observation import DEFAULT_SENSOR_GROUPS, ObservationConfig, ObservationNotReady, TianjiInsertionObservationBuilder
from .ros_topics import RosTopicIngestor


def validate_bag(bag: Path, *, rate_hz: float = 10.0, max_age_s: float = 0.25) -> dict:
    if not np.isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("rate_hz must be positive and finite")
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as exc:
        raise RuntimeError("ROS 2 bag Python packages must be sourced before running preflight") from exc

    builder = TianjiInsertionObservationBuilder(
        ObservationConfig(max_age_s=max_age_s, buffer_capacity=512)
    )
    ingestor = RosTopicIngestor(builder)
    reader = rosbag2_py.SequentialCompressionReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
        rosbag2_py.ConverterOptions("", ""),
    )
    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    missing_topics = sorted(set(ingestor.subscribed_topics) - set(topic_types))
    if missing_topics:
        raise RuntimeError(f"bag is missing required observation topics: {missing_topics}")
    message_classes = {
        topic: get_message(topic_types[topic]) for topic in ingestor.subscribed_topics
    }

    counts: Counter[str] = Counter()
    next_decision_ns: int | None = None
    period_ns = int(round(1e9 / rate_hz))
    valid_steps = 0
    rejected_steps = 0
    rejection_examples: list[str] = []
    ages: list[np.ndarray] = []
    last_observation: dict[str, np.ndarray] | None = None

    def watermark_ns() -> int | None:
        latest = [builder.buffers[name].latest_timestamp_ns for name in DEFAULT_SENSOR_GROUPS]
        if any(value is None for value in latest):
            return None
        return min(int(value) for value in latest if value is not None)

    while reader.has_next():
        topic, serialized, bag_timestamp_ns = reader.read_next()
        if topic not in message_classes:
            continue
        message = deserialize_message(serialized, message_classes[topic])
        ingestor.ingest(topic, message, received_timestamp_ns=bag_timestamp_ns)
        counts[topic] += 1
        watermark = watermark_ns()
        if watermark is None:
            continue
        if next_decision_ns is None:
            next_decision_ns = watermark
            try:
                builder.capture_grasp_baseline(next_decision_ns)
            except ObservationNotReady:
                next_decision_ns = None
                continue
        while next_decision_ns <= watermark:
            try:
                observation = builder.build(next_decision_ns)
            except ObservationNotReady as exc:
                rejected_steps += 1
                if len(rejection_examples) < 5:
                    rejection_examples.append(str(exc))
            else:
                valid_steps += 1
                ages.append(observation["sensor_age_s"])
                last_observation = observation
            next_decision_ns += period_ns

    if last_observation is None:
        raise RuntimeError("bag did not produce any valid synchronized observation")
    age_array = np.stack(ages)
    return {
        "bag": str(bag.resolve()),
        "rate_hz": rate_hz,
        "max_age_s": max_age_s,
        "baseline_timestamp_ns": builder.baseline_timestamp_ns,
        "valid_steps": valid_steps,
        "rejected_steps": rejected_steps,
        "rejection_examples": rejection_examples,
        "message_counts": dict(sorted(counts.items())),
        "sensor_order": list(DEFAULT_SENSOR_GROUPS),
        "sensor_age_s": {
            "p95": np.quantile(age_array, 0.95, axis=0).round(6).tolist(),
            "max": np.max(age_array, axis=0).round(6).tolist(),
        },
        "observation": {
            key: {"shape": list(value.shape), "dtype": str(value.dtype)}
            for key, value in last_observation.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("--rate-hz", type=float, default=10.0)
    parser.add_argument("--max-age-s", type=float, default=0.25)
    args = parser.parse_args()
    print(json.dumps(validate_bag(args.bag, rate_hz=args.rate_hz, max_age_s=args.max_age_s), indent=2))


if __name__ == "__main__":
    main()
