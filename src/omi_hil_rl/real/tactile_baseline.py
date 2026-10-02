"""Extract a zero-load tactile reference window from a ROS 2 bag.

The module keeps ROS imports lazy.  Pure NumPy aggregation and validation can
therefore be tested in the project environment without sourcing ROS.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .ros_topics import decode_image_message, gripper_value, wrench_value


DEFAULT_TOPICS = {
    "gripper": "/dm_gripper/joint_states",
    "camera": "/camera/camera/color/image_raw",
    "a_raw": "/tj/dm_sensor/a_raw",
    "b_raw": "/tj/dm_sensor/b_raw",
    "a_depth": "/tj/dm_sensor/a_depth",
    "b_depth": "/tj/dm_sensor/b_depth",
    "a_force": "/tj/dm_sensor/a_force",
    "b_force": "/tj/dm_sensor/b_force",
}


def temporal_median_uint8(frames: Iterable[np.ndarray]) -> np.ndarray:
    """Return a noise-reduced uint8 reference image from equal-shaped frames."""

    values = [np.asarray(frame) for frame in frames]
    if not values:
        raise ValueError("at least one tactile frame is required")
    shape = values[0].shape
    if len(shape) != 2 or any(value.shape != shape for value in values):
        raise ValueError("all tactile frames must have the same HxW shape")
    if any(value.dtype != np.uint8 for value in values):
        raise ValueError("tactile reference frames must be uint8")
    return np.rint(np.median(np.stack(values), axis=0)).astype(np.uint8)


def raw_stability(frames: Iterable[np.ndarray]) -> dict[str, float]:
    """Summarize brightness drift and frame-to-frame pixel noise."""

    values = [np.asarray(frame, dtype=np.float32) for frame in frames]
    if not values:
        raise ValueError("at least one tactile frame is required")
    means = np.asarray([value.mean() for value in values], dtype=np.float64)
    successive = [
        float(np.mean(np.abs(current - previous)))
        for previous, current in zip(values, values[1:])
    ]
    return {
        "pixel_mean": float(means.mean()),
        "pixel_mean_std_over_time": float(means.std()),
        "successive_frame_mae": float(np.mean(successive)) if successive else 0.0,
    }


def zero_load_checks(
    *,
    gripper_positions: Iterable[float],
    wrench_a: Iterable[np.ndarray],
    wrench_b: Iterable[np.ndarray],
    depth_means_a: Iterable[float],
    depth_means_b: Iterable[float],
    min_open_position: float = 0.95,
    max_force_norm: float = 1.0,
    max_depth_mean: float = 0.02,
) -> dict[str, Any]:
    """Apply explicit record-validation heuristics to a candidate window."""

    gripper = np.asarray(list(gripper_positions), dtype=np.float64)
    force_a = np.asarray(list(wrench_a), dtype=np.float64)
    force_b = np.asarray(list(wrench_b), dtype=np.float64)
    depth_a = np.asarray(list(depth_means_a), dtype=np.float64)
    depth_b = np.asarray(list(depth_means_b), dtype=np.float64)
    if gripper.size == 0 or force_a.size == 0 or force_b.size == 0:
        raise ValueError("gripper and both wrench streams are required")
    if depth_a.size == 0 or depth_b.size == 0:
        raise ValueError("both depth streams are required")
    if force_a.ndim != 2 or force_b.ndim != 2 or force_a.shape[1] < 3 or force_b.shape[1] < 3:
        raise ValueError("each wrench stream must contain vectors with at least three force values")
    force_norm_a = np.linalg.norm(force_a[:, :3], axis=1)
    force_norm_b = np.linalg.norm(force_b[:, :3], axis=1)
    measured = {
        "gripper_position_min": float(gripper.min()),
        "gripper_position_mean": float(gripper.mean()),
        "force_norm_mean_a": float(force_norm_a.mean()),
        "force_norm_mean_b": float(force_norm_b.mean()),
        "depth_mean_a": float(depth_a.mean()),
        "depth_mean_b": float(depth_b.mean()),
    }
    checks = {
        "gripper_open": measured["gripper_position_min"] >= min_open_position,
        "force_a_near_zero": measured["force_norm_mean_a"] <= max_force_norm,
        "force_b_near_zero": measured["force_norm_mean_b"] <= max_force_norm,
        "depth_a_near_zero": measured["depth_mean_a"] <= max_depth_mean,
        "depth_b_near_zero": measured["depth_mean_b"] <= max_depth_mean,
    }
    return {
        "thresholds": {
            "min_open_position": min_open_position,
            "max_force_norm": max_force_norm,
            "max_depth_mean": max_depth_mean,
        },
        "measured": measured,
        "checks": checks,
        "all_passed": all(checks.values()),
    }


def _save_contact_sheet(samples: dict[float, tuple[float, np.ndarray]], path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required to save baseline preview images") from exc

    tiles = []
    for target in sorted(samples):
        actual, rgb = samples[target]
        image = Image.fromarray(rgb, mode="RGB")
        image.thumbnail((384, 288))
        tile = Image.new("RGB", (384, 320), "black")
        tile.paste(image, ((384 - image.width) // 2, 32))
        ImageDraw.Draw(tile).text((8, 8), f"target={target:.2f}s actual={actual:.2f}s", fill="white")
        tiles.append(tile)
    if not tiles:
        raise ValueError("camera preview requires at least one sample")
    sheet = Image.new("RGB", (384 * len(tiles), 320), "black")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (384 * index, 0))
    sheet.save(path)


def extract_tactile_baseline(
    bag: Path,
    output_dir: Path,
    *,
    start_s: float,
    end_s: float,
    serial_a: str | None = None,
    serial_b: str | None = None,
    physical_side_a: str | None = None,
    physical_side_b: str | None = None,
) -> dict[str, Any]:
    """Extract median A/B raw references and a validation report."""

    if not np.isfinite(start_s) or not np.isfinite(end_s) or start_s < 0 or end_s <= start_s:
        raise ValueError("expected 0 <= start_s < end_s")
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output_dir}")
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as exc:
        raise RuntimeError("source ROS 2 before extracting a tactile baseline") from exc

    reader = rosbag2_py.SequentialCompressionReader() if bag.is_dir() else rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    topic_types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    missing = sorted(set(DEFAULT_TOPICS.values()) - set(topic_types))
    if missing:
        raise RuntimeError(f"bag is missing baseline-validation topics: {missing}")
    message_types = {
        topic: get_message(topic_types[topic]) for topic in DEFAULT_TOPICS.values()
    }

    raw_frames: dict[str, list[np.ndarray]] = {"a_raw": [], "b_raw": []}
    raw_timestamps: dict[str, list[int]] = {"a_raw": [], "b_raw": []}
    depth_means: dict[str, list[float]] = {"a_depth": [], "b_depth": []}
    wrenches: dict[str, list[np.ndarray]] = {"a_force": [], "b_force": []}
    gripper_positions: list[float] = []
    camera_targets = np.linspace(start_s, end_s, 5)
    camera_samples: dict[float, tuple[float, np.ndarray]] = {}
    first_bag_timestamp_ns: int | None = None

    topic_keys = {topic: key for key, topic in DEFAULT_TOPICS.items()}
    while reader.has_next():
        topic, serialized, bag_timestamp_ns = reader.read_next()
        if first_bag_timestamp_ns is None:
            first_bag_timestamp_ns = int(bag_timestamp_ns)
        relative_s = (int(bag_timestamp_ns) - first_bag_timestamp_ns) / 1e9
        if relative_s > end_s + 0.5:
            break
        if topic not in message_types:
            continue
        key = topic_keys[topic]
        message = deserialize_message(serialized, message_types[topic])
        if key == "camera":
            rgb = decode_image_message(message)
            for target in camera_targets:
                target_f = float(target)
                old = camera_samples.get(target_f)
                if old is None or abs(relative_s - target_f) < abs(old[0] - target_f):
                    camera_samples[target_f] = (relative_s, rgb)
            continue
        if not start_s <= relative_s <= end_s:
            continue
        if key in raw_frames:
            image = decode_image_message(message)
            if image.dtype != np.uint8 or image.ndim != 2:
                raise ValueError(f"{topic} must be a mono8 HxW image")
            raw_frames[key].append(image)
            raw_timestamps[key].append(int(bag_timestamp_ns))
        elif key in depth_means:
            depth = np.asarray(decode_image_message(message), dtype=np.float32)
            finite = depth[np.isfinite(depth)]
            if finite.size == 0:
                raise ValueError(f"{topic} contains no finite values")
            depth_means[key].append(float(finite.mean()))
        elif key in wrenches:
            wrenches[key].append(wrench_value(message))
        elif key == "gripper":
            gripper_positions.append(gripper_value(message))

    if first_bag_timestamp_ns is None:
        raise RuntimeError("bag contains no messages")
    base_a = temporal_median_uint8(raw_frames["a_raw"])
    base_b = temporal_median_uint8(raw_frames["b_raw"])
    validation = zero_load_checks(
        gripper_positions=gripper_positions,
        wrench_a=wrenches["a_force"],
        wrench_b=wrenches["b_force"],
        depth_means_a=depth_means["a_depth"],
        depth_means_b=depth_means["b_depth"],
    )

    output_dir.mkdir(parents=True)
    np.save(output_dir / "tactile_a_base.npy", base_a)
    np.save(output_dir / "tactile_b_base.npy", base_b)
    np.savez_compressed(
        output_dir / "tactile_baseline.npz",
        tactile_a_base=base_a,
        tactile_b_base=base_b,
        tactile_a_timestamps_ns=np.asarray(raw_timestamps["a_raw"], dtype=np.int64),
        tactile_b_timestamps_ns=np.asarray(raw_timestamps["b_raw"], dtype=np.int64),
    )
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to save baseline preview images") from exc
    Image.fromarray(base_a, mode="L").save(output_dir / "tactile_a_base.png")
    Image.fromarray(base_b, mode="L").save(output_dir / "tactile_b_base.png")
    _save_contact_sheet(camera_samples, output_dir / "open_gripper_contact_sheet.png")

    report = {
        "schema_version": 1,
        "bag": str(bag.resolve()),
        "bag_start_timestamp_ns": first_bag_timestamp_ns,
        "window": {"start_s": start_s, "end_s": end_s, "aggregation": "temporal_median"},
        "topics": DEFAULT_TOPICS,
        "sensor_identity": {
            "tactile_a": {"serial": serial_a, "physical_side": physical_side_a},
            "tactile_b": {"serial": serial_b, "physical_side": physical_side_b},
        },
        "raw": {
            "tactile_a": {
                "count": len(raw_frames["a_raw"]),
                "shape": list(base_a.shape),
                "dtype": str(base_a.dtype),
                "stability": raw_stability(raw_frames["a_raw"]),
            },
            "tactile_b": {
                "count": len(raw_frames["b_raw"]),
                "shape": list(base_b.shape),
                "dtype": str(base_b.dtype),
                "stability": raw_stability(raw_frames["b_raw"]),
            },
        },
        "sample_counts": {
            "gripper": len(gripper_positions),
            "a_depth": len(depth_means["a_depth"]),
            "b_depth": len(depth_means["b_depth"]),
            "a_force": len(wrenches["a_force"]),
            "b_force": len(wrenches["b_force"]),
        },
        "zero_load_validation": validation,
        "limitations": [
            (
                "The bag does not store tactile identity; the serial and physical-side mapping was supplied externally."
                if serial_a and serial_b and physical_side_a and physical_side_b
                else "The bag does not store tactile identity; A/B serial or physical-side mapping remains unresolved."
            ),
            "Force units are not asserted because the vendor SDK documentation does not specify them.",
            "The thresholds are record-validation heuristics, not sensor calibration limits.",
        ],
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path, help="ROS 2 bag directory or an uncompressed .mcap file")
    parser.add_argument("output_dir", type=Path, help="new directory for local baseline artifacts")
    parser.add_argument("--start-s", type=float, default=25.0)
    parser.add_argument("--end-s", type=float, default=26.0)
    parser.add_argument("--serial-a", help="optional confirmed vendor serial for tactile A")
    parser.add_argument("--serial-b", help="optional confirmed vendor serial for tactile B")
    parser.add_argument("--physical-side-a", choices=("left", "right"))
    parser.add_argument("--physical-side-b", choices=("left", "right"))
    args = parser.parse_args()
    report = extract_tactile_baseline(
        args.bag,
        args.output_dir,
        start_s=args.start_s,
        end_s=args.end_s,
        serial_a=args.serial_a,
        serial_b=args.serial_b,
        physical_side_a=args.physical_side_a,
        physical_side_b=args.physical_side_b,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
