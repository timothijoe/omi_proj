#!/usr/bin/env python3
"""Offline acceptance: synthetic publishers -> recorder -> reader -> replay subscriber.

Run with the ROS overlay sourced. Never imports SDK or opens a camera. Evidence
is saved to a unique directory under the provided existing output root.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import numpy as np
import rclpy
from rclpy.serialization import deserialize_message
import rosbag2_py
from rosidl_runtime_py.utilities import get_message
from sensor_msgs.msg import Image

from omi_sensors.config import load_config, sensor_topics
from omi_sensors.cli import environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    config["domain_id"] = 89
    folder = Path(tempfile.mkdtemp(prefix="sensors-smoke-", dir=args.output_root))
    conf = folder / "config.json"
    conf.write_text(json.dumps(config))
    os.environ.update(environment(config))
    base = [sys.executable, "-m", "omi_sensors.cli", "--config", str(conf)]
    processes = []
    replay, node = None, None
    try:
        recorder = subprocess.Popen(base + ["record", str(folder / "session"), "--duration", "8"])
        processes.append(recorder)
        time.sleep(1)
        fake = subprocess.Popen(base + ["fake", "--duration", "6"])
        processes.append(fake)
        assert fake.wait(timeout=20) == 0
        assert recorder.wait(timeout=20) == 0
        bag = folder / "session/bag"
        reader = rosbag2_py.SequentialReader()
        reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"), rosbag2_py.ConverterOptions("", ""))
        types = {item.name: get_message(item.type) for item in reader.get_all_topics_and_types()}
        counts, groups = {}, {}
        while reader.has_next():
            topic, data, stamp = reader.read_next()
            counts[topic] = counts.get(topic, 0) + 1
            msg = deserialize_message(data, types[topic])
            if topic.endswith("/metadata"):
                metadata = json.loads(msg.data)
                assert metadata["processing_version"] == "synthetic-v1"
                assert metadata["timestamp_kind"] == "synthetic_host_time"
            elif topic.endswith(("/deformation", "/shear")):
                assert msg.encoding == "32FC2"
                assert len(msg.data) == msg.height * msg.width * 8
                assert np.isfinite(np.frombuffer(bytes(msg.data), dtype="<f4")).all()
            if hasattr(msg, "header"):
                stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
                groups.setdefault(stamp, set()).add(topic)
        del reader
        required = set(sensor_topics(config))
        assert set(counts) == required, (set(counts), required)
        assert all(count >= 3 for count in counts.values()), counts
        camera_pair = {"/camera/camera/color/image_raw", "/camera/camera/color/camera_info"}
        assert any(camera_pair <= topics for topics in groups.values())
        rclpy.init(args=[])
        node = rclpy.create_node("omi_smoke_replay_check")
        received = []
        node.create_subscription(Image, "/omi/tactile/a/deformation", lambda msg: received.append(msg), 10)
        replay = subprocess.Popen(base + ["replay", str(bag)])
        processes.append(replay)
        deadline = time.monotonic() + 15
        while replay.poll() is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        assert replay.wait(timeout=5) == 0
        assert len(received) >= 10, len(received)
        report = {"passed": True, "counts": counts, "replayed_deformation_messages": len(received),
                  "validation": "synthetic only; no hardware or Humble runtime tested", "ros_distro": os.environ.get("ROS_DISTRO")}
        (folder / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"evidence": str(folder), **report}, indent=2))
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
