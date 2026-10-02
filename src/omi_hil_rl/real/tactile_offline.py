"""Probe Daimon tactile fields from rosbag raw images without device access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

from .ros_topics import decode_image_message, wrench_value
from .tactile_vectors import render_vector_field


TOPICS = {
    "a": {
        "raw": "/tj/dm_sensor/a_raw",
        "depth": "/tj/dm_sensor/a_depth",
        "force": "/tj/dm_sensor/a_force",
    },
    "b": {
        "raw": "/tj/dm_sensor/b_raw",
        "depth": "/tj/dm_sensor/b_depth",
        "force": "/tj/dm_sensor/b_force",
    },
}


def numeric_stats(value: np.ndarray) -> dict[str, Any]:
    array = np.asarray(value)
    finite = array[np.isfinite(array)]
    if finite.size != array.size:
        raise ValueError("array contains NaN or Inf")
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "min": float(finite.min()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
        "std": float(finite.std()),
    }


def depth_comparison(reconstructed: np.ndarray, recorded: np.ndarray) -> dict[str, float]:
    left = np.asarray(reconstructed, dtype=np.float64)
    right = np.asarray(recorded, dtype=np.float64)
    if left.shape != right.shape:
        raise ValueError("reconstructed and recorded depth shapes differ")
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ValueError("depth comparison contains NaN or Inf")
    delta = left - right
    left_flat = left.ravel()
    right_flat = right.ravel()
    if left_flat.std() == 0 or right_flat.std() == 0:
        correlation = 1.0 if np.array_equal(left_flat, right_flat) else 0.0
    else:
        correlation = float(np.corrcoef(left_flat, right_flat)[0, 1])
    denominator = float(np.dot(left_flat, left_flat))
    scale_to_recorded = float(np.dot(left_flat, right_flat) / denominator) if denominator else 0.0
    return {
        "mae": float(np.mean(np.abs(delta))),
        "rmse": float(np.sqrt(np.mean(delta * delta))),
        "pearson": correlation,
        "least_squares_scale_reconstructed_to_recorded": scale_to_recorded,
    }


def _nearest_resize(image: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    rows = np.rint(np.linspace(0, image.shape[0] - 1, shape[0])).astype(int)
    cols = np.rint(np.linspace(0, image.shape[1] - 1, shape[1])).astype(int)
    return image[rows[:, None], cols[None, :]]


def _depth_rgb(depth: np.ndarray, maximum: float = 0.35) -> np.ndarray:
    normalized = np.clip(np.asarray(depth, dtype=np.float32) / maximum, 0, 1)
    red = np.rint(255 * normalized).astype(np.uint8)
    blue = 255 - red
    green = np.rint(255 * (1 - np.abs(2 * normalized - 1))).astype(np.uint8)
    return np.stack((red, green, blue), axis=-1)


def _save_dashboard(panels: list[tuple[str, np.ndarray]], path: Path) -> None:
    from PIL import Image, ImageDraw

    tiles = []
    for label, value in panels:
        image = Image.fromarray(value, mode="RGB")
        tile = Image.new("RGB", (image.width, image.height + 28), "black")
        tile.paste(image, (0, 28))
        ImageDraw.Draw(tile).text((8, 7), label, fill="white")
        tiles.append(tile)
    columns = len(tiles) // 2
    width = sum(tile.width for tile in tiles[:columns])
    height = tiles[0].height + tiles[columns].height
    sheet = Image.new("RGB", (width, height), "black")
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        x = sum(item.width for item in tiles[row * columns : row * columns + column])
        y = row * tile.height
        sheet.paste(tile, (x, y))
    sheet.save(path)


def probe_bag(
    bag: Path,
    baseline_dir: Path,
    output_dir: Path,
    *,
    sdk_root: Path,
    target_times_s: tuple[float, ...],
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output_dir}")
    if not target_times_s or any(not np.isfinite(x) or x < 0 for x in target_times_s):
        raise ValueError("target times must be finite and nonnegative")
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as exc:
        raise RuntimeError("source ROS 2 before running the offline tactile probe") from exc

    sdk_root = sdk_root.resolve()
    if not (sdk_root / "dmrobotics").is_dir():
        raise FileNotFoundError(f"Daimon SDK package not found under {sdk_root}")
    sys.path.insert(0, str(sdk_root))
    try:
        from dmrobotics.src.dmSDK import Decomposer, FlowTracker, NormalFromFlowCached
    except ImportError as exc:
        raise RuntimeError("Daimon SDK dependencies are incomplete") from exc

    reader = rosbag2_py.SequentialCompressionReader() if bag.is_dir() else rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    topic_types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    all_topics = {topic for side in TOPICS.values() for topic in side.values()}
    missing = sorted(all_topics - set(topic_types))
    if missing:
        raise RuntimeError(f"bag is missing tactile probe topics: {missing}")
    message_types = {topic: get_message(topic_types[topic]) for topic in all_topics}
    reverse = {
        topic: (side, kind)
        for side, streams in TOPICS.items()
        for kind, topic in streams.items()
    }
    samples: dict[str, dict[str, dict[float, tuple[float, Any]]]] = {
        side: {kind: {} for kind in streams} for side, streams in TOPICS.items()
    }
    first_ns = None
    while reader.has_next():
        topic, serialized, stamp_ns = reader.read_next()
        if first_ns is None:
            first_ns = int(stamp_ns)
        relative_s = (int(stamp_ns) - first_ns) / 1e9
        if relative_s > max(target_times_s) + 0.5:
            break
        if topic not in reverse:
            continue
        side, kind = reverse[topic]
        message = deserialize_message(serialized, message_types[topic])
        value = wrench_value(message) if kind == "force" else decode_image_message(message)
        for target in target_times_s:
            old = samples[side][kind].get(target)
            if old is None or abs(relative_s - target) < abs(old[0] - target):
                samples[side][kind][target] = (relative_s, value)

    output_dir.mkdir(parents=True)
    baseline_metadata_path = baseline_dir / "metadata.json"
    baseline_metadata = (
        json.loads(baseline_metadata_path.read_text(encoding="utf-8"))
        if baseline_metadata_path.is_file()
        else None
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "bag": str(bag.resolve()),
        "baseline_dir": str(baseline_dir.resolve()),
        "sdk_root": str(sdk_root),
        "backend": "cpu",
        "serial_required": False,
        "sensor_identity": None if baseline_metadata is None else baseline_metadata.get("sensor_identity"),
        "renderer": {"step": 16, "scale_px_per_unit": 2.0, "deadband": 0.2, "max_arrow_px": 24.0},
        "targets": {},
    }
    normal = NormalFromFlowCached(backend="cpu")
    dashboards: dict[float, list[tuple[str, np.ndarray]]] = {target: [] for target in target_times_s}
    for side in ("a", "b"):
        base = np.load(baseline_dir / f"tactile_{side}_base.npy")
        tracker = FlowTracker(backend="cpu", model_path="standard")
        tracker.setBaseFrame(base)
        side_report = report["targets"].setdefault(side, {})
        for target in target_times_s:
            raw_time, raw = samples[side]["raw"][target]
            depth_time, recorded_depth = samples[side]["depth"][target]
            force_time, recorded_force = samples[side]["force"][target]
            deformation = np.asarray(tracker.t(raw), dtype=np.float32)
            reconstructed_depth = np.asarray(normal(deformation), dtype=np.float32)
            shear = np.asarray(
                Decomposer(deformation.shape[:2], (1, 1), "cpu").decompose(deformation),
                dtype=np.float32,
            )
            background = _nearest_resize(raw, deformation.shape[:2])
            deformation_rgb, deformation_render = render_vector_field(
                deformation,
                background=background,
                step=16,
                scale_px_per_unit=2.0,
                deadband=0.2,
                max_arrow_px=24.0,
            )
            shear_rgb, shear_render = render_vector_field(
                shear,
                background=background,
                step=16,
                scale_px_per_unit=2.0,
                deadband=0.2,
                max_arrow_px=24.0,
            )
            stem = f"{side}_{target:.2f}s"
            np.savez_compressed(
                output_dir / f"{stem}.npz",
                raw=raw,
                deformation=deformation,
                shear=shear,
                reconstructed_depth=reconstructed_depth,
                recorded_depth=recorded_depth,
                recorded_wrench=recorded_force,
            )
            from PIL import Image

            Image.fromarray(deformation_rgb, mode="RGB").save(output_dir / f"{stem}_deformation.png")
            Image.fromarray(shear_rgb, mode="RGB").save(output_dir / f"{stem}_shear.png")
            side_report[f"{target:.2f}"] = {
                "actual_times_s": {"raw": raw_time, "depth": depth_time, "force": force_time},
                "deformation": numeric_stats(deformation),
                "shear": numeric_stats(shear),
                "reconstructed_depth": numeric_stats(reconstructed_depth),
                "recorded_depth": numeric_stats(recorded_depth),
                "depth_comparison": depth_comparison(reconstructed_depth, recorded_depth),
                "recorded_wrench": np.asarray(recorded_force).round(7).tolist(),
                "deformation_render": deformation_render.as_dict(),
                "shear_render": shear_render.as_dict(),
            }
            raw_rgb = np.repeat(background[..., None], 3, axis=2)
            dashboards[target].extend(
                [
                    (f"{side.upper()} raw", raw_rgb),
                    (f"{side.upper()} deformation", deformation_rgb),
                    (f"{side.upper()} shear", shear_rgb),
                    (f"{side.upper()} reconstructed depth", _depth_rgb(reconstructed_depth)),
                    (f"{side.upper()} recorded depth", _depth_rgb(recorded_depth)),
                ]
            )
        tracker.close()
    for target, panels in dashboards.items():
        _save_dashboard(panels, output_dir / f"dashboard_{target:.2f}s.png")
    report["limitations"] = [
        "Deformation and shear have no recorded topic in record010 for direct comparison.",
        "Reconstructed depth uses SDK default CPU parameters and is not assumed identical to the online producer.",
        (
            "Vendor physical units remain unconfirmed; sensor identity was supplied externally rather than stored in the bag."
            if report["sensor_identity"]
            else "Vendor physical units and A/B sensor identity remain unconfirmed."
        ),
    ]
    (output_dir / "metadata.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("baseline_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--sdk-root", type=Path, required=True, help="directory containing dmrobotics/")
    parser.add_argument("--target-s", type=float, action="append", dest="targets")
    args = parser.parse_args()
    targets = tuple(args.targets or (23.0, 25.5, 28.0))
    report = probe_bag(
        args.bag,
        args.baseline_dir,
        args.output_dir,
        sdk_root=args.sdk_root,
        target_times_s=targets,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
