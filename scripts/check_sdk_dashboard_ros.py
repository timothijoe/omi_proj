#!/usr/bin/env python3
"""Headless SDK-native dashboard acceptance; synthetic input only, no hardware.

Exercises the public shell entry, recording, stale indication, bag replay loops,
matching CameraInfo, and shutdown. Outputs evidence in a unique local directory.
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
from PIL import Image as PillowImage
import rclpy
from sensor_msgs.msg import Image
from std_msgs.msg import String

from omi_sensors.cli import environment
from omi_sensors.config import load_config
from omi_sensors.dashboard import decode_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(args.config)
    cfg["domain_id"] = 91
    output = Path(tempfile.mkdtemp(prefix="sdk-dashboard-check-", dir=args.output_root.resolve()))
    path = output / "config.json"
    path.write_text(json.dumps(cfg))
    os.environ.update(environment(cfg))
    base = [sys.executable, "-m", "omi_sensors.cli", "--config", str(path)]
    viewer = ["bash", str(root / "scripts/view_sdk_observation.sh"), "--config", str(path), "--no-rviz"]
    children, files = [], []
    latest, states = {}, []
    image_count = 0
    rclpy.init(args=[])
    node = rclpy.create_node("omi_sdk_dashboard_acceptance")

    def on_image(msg):
        nonlocal image_count
        array = decode_image(msg)
        assert array.shape == (1000, 1536, 3) and array.dtype == np.uint8
        latest["image"] = array
        image_count += 1

    def on_status(msg):
        status = json.loads(msg.data)
        latest["status"] = status
        states.append(status)

    node.create_subscription(Image, "/omi/sdk/dashboard", on_image, 2)
    node.create_subscription(String, "/omi/sdk/dashboard_status", on_status, 10)

    def launch(command, name):
        log = (output / (name + ".log")).open("w")
        files.append(log)
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        children.append(process)
        return process

    def until(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if predicate():
                return
        raise AssertionError("acceptance timeout; last status=" + str(latest.get("status")))

    def stop(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=20)

    try:
        view = launch(viewer, "viewer-live")
        until(lambda: latest.get("status", {}).get("sides", {}).get("a", {}).get("state") == "WAITING", 10)
        record = launch(base + ["record", str(output / "session"), "--duration", "7"], "record")
        fake = launch(base + ["fake", "--duration", "5"], "fake")
        until(lambda: all(latest.get("status", {}).get("sides", {}).get(s, {}).get("state") == "SYNTHETIC" for s in ("a", "b"))
              and latest["status"]["camera"]["intrinsics_matched"] and image_count >= 5, 10)
        # Wait for a few more frames so the image and summary both describe live data.
        before = image_count
        until(lambda: image_count >= before + 3, 5)
        PillowImage.fromarray(latest["image"]).save(output / "live.png")
        until(lambda: fake.poll() is not None and record.poll() is not None
              and all(latest["status"]["sides"][s]["state"] == "STALE" for s in ("a", "b")), 12)
        assert fake.returncode == 0 and record.returncode == 0
        assert latest["status"]["camera"]["state"] == "STALE"
        before = image_count
        until(lambda: image_count >= before + 2, 5)
        PillowImage.fromarray(latest["image"]).save(output / "stale.png")
        live_status = latest["status"]
        stop(view)
        replay = launch(viewer + ["--bag", str(output / "session/bag"), "--loop", "--rate", "2", "--duration", "8"], "viewer-replay")
        until(lambda: all(latest["status"]["sides"][s]["epochs"] >= 1 for s in ("a", "b")), 12)
        replay_status = latest["status"]
        until(lambda: replay.poll() is not None, 12)
        assert replay.returncode == 0
        assert all(p.poll() is not None for p in children)
        report = {"passed": True, "synthetic_only": True, "image_messages": image_count,
                  "live_then_stale": live_status, "loop_replay": replay_status,
                  "all_owned_supervisors_exited": True,
                  "SDK_not_loaded": "dmrobotics" not in sys.modules, "ros_distro": os.environ.get("ROS_DISTRO")}
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"evidence": str(output), "passed": True, "images": image_count}))
    finally:
        for process in children:
            if process.poll() is None:
                try:
                    stop(process)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
        for file in files:
            file.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
