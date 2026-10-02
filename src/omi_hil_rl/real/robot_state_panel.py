"""Read-only bag robot-state timeline and opt-in observation image compositor.

Robot commands are decoded offline, NEVER published or replayed on ROS topics.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np

TOPICS = {
    "/tj/info/joint_feedback": "feedback",
    "/tj/control/joint_cmd_A": "target",
    "/dm_gripper/joint_states": "gripper",
    "/tj/control/gripperValueL": "gripper_command",
}
HEIGHT = 340


def decode_record(kind, message, bag_stamp):
    header = getattr(message, "header", None)
    stamp = 0 if header is None else header.stamp.sec * 10**9 + header.stamp.nanosec
    clock = "header" if stamp > 0 else "bag_receive"
    stamp = stamp if stamp > 0 else bag_stamp
    if kind == "feedback":
        values = {k: np.asarray(getattr(message, "arm_" + k), dtype=float)
                  for k in ("positions", "velocities", "efforts")}
        if any(v.shape != (14,) for v in values.values()):
            raise ValueError("feedback must contain 14 joints")
    else:
        attr = {"target": "positions", "gripper": "position", "gripper_command": "data"}[kind]
        values = {"positions": np.asarray(getattr(message, attr), dtype=float).reshape(-1)}
        n = values["positions"].size
        if n == 0 or (kind == "target" and n != 7):
            raise ValueError("invalid robot state shape")
    if stamp <= 0 or any(not np.isfinite(v).all() for v in values.values()):
        raise ValueError("invalid robot timestamp or nonfinite state")
    return dict(stamp=int(stamp), clock=clock, values={k: v.tolist() for k, v in values.items()})


def prepare(bag, cache_root):
    import yaml
    bag, cache_root = Path(bag).resolve(), Path(cache_root).resolve()
    metadata = (bag / "metadata.yaml").read_bytes()
    info = yaml.safe_load(metadata)["rosbag2_bagfile_information"]
    if info["storage_identifier"] != "mcap":
        raise ValueError("This legacy robot viewer currently supports MCAP bags")
    mode = info.get("compression_mode", "").lower()
    if mode not in ("", "none", "file") or (mode == "file" and info.get("compression_format") != "zstd"):
        raise ValueError("Only uncompressed or file-zstd MCAP is supported")
    files = [(bag / p).resolve() for p in info["relative_file_paths"]]
    if any(not p.is_relative_to(bag) or not p.is_file() for p in files):
        raise ValueError("Invalid bag source paths")
    signature = dict(version=1, source=str(bag), metadata=hashlib.sha256(metadata).hexdigest(),
                     files=[(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files])
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
    cache_root.mkdir(parents=True, exist_ok=True)
    output = cache_root / (key + ".json")
    if output.is_file():
        return output
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    records = {kind: [] for kind in TOPICS.values()}
    rejected = {kind: 0 for kind in TOPICS.values()}
    with tempfile.TemporaryDirectory(prefix="robot-read-", dir=cache_root) as tmp:
        for index, source in enumerate(files):
            path = source
            if mode == "file":
                path = Path(tmp) / (str(index) + ".mcap")
                with path.open("xb") as stream:
                    subprocess.run(["zstd", "-d", "-c", "--", str(source)], stdout=stream, check=True)
            reader = rosbag2_py.SequentialReader()
            reader.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="mcap"),
                        rosbag2_py.ConverterOptions("cdr", "cdr"))
            classes = {t.name: get_message(t.type) for t in reader.get_all_topics_and_types() if t.name in TOPICS}
            # An empty storage filter would read every image. Skip absent robot topics.
            if classes:
                reader.set_filter(rosbag2_py.StorageFilter(topics=list(classes)))
                while reader.has_next():
                    topic, data, stamp = reader.read_next()
                    kind = TOPICS[topic]
                    try:
                        records[kind].append(decode_record(kind, deserialize_message(data, classes[topic]), stamp))
                    except (ValueError, TypeError, AttributeError):
                        rejected[kind] += 1
            del reader
            if path != source:
                path.unlink()
        if not any(records.values()):
            raise ValueError("No valid robot records; verify bag and matching marvin_msgs")
        for entries in records.values():
            entries.sort(key=lambda x: x["stamp"])
        staged = Path(tmp) / "timeline.json"
        staged.write_text(json.dumps(dict(signature=signature, records=records, rejected=rejected)))
        staged.replace(output)
    return output


class Timeline:
    def __init__(self, records):
        self.records = records
        self.stamps = {k: [v["stamp"] for v in items] for k, items in records.items()}

    def at(self, kind, stamp, max_age_s=0.25):
        index = bisect_right(self.stamps.get(kind, []), stamp) - 1
        if index < 0:
            return None, "WAITING", None
        item = self.records[kind][index]
        age = (stamp - item["stamp"]) / 1e9
        return item, "STALE" if age > max_age_s else "VALID", age


def panel(timeline, stamp, width, wall_age=0.0):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (width, HEIGHT), (18, 20, 24))
    draw = ImageDraw.Draw(canvas)
    def text(y, value, color="white"):
        draw.text((12, y), value, fill=color)
    text(8, "ROBOT STATE | READ-ONLY BAG DATA | TCP pose: NOT RECORDED (no FK)")
    text(26, f"Reference = observation dashboard header: {stamp} | latest state <= reference; NOT exact camera/tactile sync")
    text(44, f"Reference unchanged for {wall_age:.2f}s | " + ("STALE / PAUSED" if wall_age > .5 else "LIVE REPLAY"),
         "orange" if wall_age > .5 else "white")
    text(62, "Values shown AS RECORDED; units not verified. Feedback order L1..L7,R1..R7; target A mapping unverified.")
    def row(kind, y, label):
        item, state, age = timeline.at(kind, stamp)
        if wall_age > .5 and item is not None:
            state = "STALE"
        suffix = "" if item is None else f" | lag={age:.3f}s | time={item['clock']} | source_ns={item['stamp']}"
        text(y, label + " | " + state + suffix, "orange" if state != "VALID" else "#78e5a0")
        return item
    item = row("feedback", 88, "JOINT FEEDBACK")
    if item:
        q = item["values"]["positions"]
        text(106, "L1..L7: " + "  ".join(f"{v:+.4f}" for v in q[:7]))
        text(124, "R1..R7: " + "  ".join(f"{v:+.4f}" for v in q[7:]))
    item = row("target", 150, "JOINT TARGET A (not replayed)")
    if item:
        text(168, "A1..A7: " + "  ".join(f"{v:+.4f}" for v in item["values"]["positions"]))
    item = row("gripper", 194, "GRIPPER FEEDBACK")
    if item:
        text(212, "position: " + str(item["values"]["positions"]))
    item = row("gripper_command", 238, "GRIPPER COMMAND L (not replayed; bag receive time fallback)")
    if item:
        text(256, "value: " + str(item["values"]["positions"]))
    text(292, "Missing data stays WAITING; stale values remain visible and flagged. No unit conversion, command publishing or robot connection.")
    text(310, "Robot fields are sampled independently; source timestamps and lag shown above. Bag loop/seek selects history anew.")
    return np.asarray(canvas).copy()


def run(path):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy._rclpy_pybind11 import RCLError
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
    from .ros_topics import decode_image_message
    from .tactile_live import image_message, stamp_ns
    timeline = Timeline(json.loads(Path(path).read_text())["records"])
    rclpy.init()
    node = rclpy.create_node("omi_robot_observation_panel")
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
    publisher = node.create_publisher(Image, "/omi/observation_robot/dashboard", qos)
    latest = []
    def receive(msg):
        try:
            if stamp_ns(msg.header) <= 0:
                raise ValueError("Nonpositive observation header")
            pixels = decode_image_message(msg)
            if pixels.ndim != 3 or pixels.shape[2] != 3:
                raise ValueError("Expected RGB observation dashboard")
            # The old dashboard can keep publishing a frozen header after bag end.
            # Repeated messages must not make historical robot state look fresh.
            progressed = time.monotonic()
            if latest and stamp_ns(latest[1]) == stamp_ns(msg.header):
                progressed = latest[2]
            latest[:] = [pixels, msg.header, progressed]
        except ValueError as exc:
            node.get_logger().error(str(exc))
    node.create_subscription(Image, "/omi/observation/dashboard", receive, qos)
    def render():
        if latest:
            pixels, header, received = latest
            bottom = panel(timeline, stamp_ns(header), pixels.shape[1], time.monotonic() - received)
            publisher.publish(image_message(np.concatenate((pixels, bottom), axis=0), header, "rgb8"))
    node.create_timer(.1, render)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        # SIGTERM can invalidate the context while the timer is publishing.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("bag", type=Path)
    prep.add_argument("cache", type=Path)
    view = sub.add_parser("view")
    view.add_argument("timeline", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(prepare(args.bag, args.cache))
    else:
        run(args.timeline)


if __name__ == "__main__":
    main()
