"""Deterministic 6D increment bags and a DDS-to-mock-controller integration test.

No hardware imports, connections, inverse kinematics, or real motion commands.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np

from omi_hil_rl.training.eef_action import apply, between, pose

ACTION_TOPIC = "/omi/action_test/decision"
TARGET_TOPIC = "/omi/action_test/mock_target"
LABEL = "left-eef-base-delta-v1:dx,dy,dz[m];rx,ry,rz[rad]"
IDENTITY = [0., 0., 0., 0., 0., 0., 1.]


def trajectory(hz=10., seconds=2., distance=.05, angle_deg=10., right_sign=-1):
    """Quintic segment profiles, followed by exact reverse-order inverses."""
    values = np.array([hz, seconds, distance, angle_deg], dtype=float)
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("Parameters must be finite and positive")
    if hz > 200 or seconds > 60 or distance > .05 or angle_deg > 30:
        raise ValueError("Experiment limits: 200 Hz, 60 s, 0.05 m, 30 degrees")
    n = round(hz * seconds)
    if n < 2 or not math.isclose(n, hz * seconds, abs_tol=1e-9):
        raise ValueError("hz * seconds must be an integer >= 2")
    if right_sign not in (-1, 1):
        raise ValueError("right_sign must be -1 or +1")
    u = np.linspace(0., 1., n + 1)
    weights = np.diff(10*u**3 - 15*u**4 + 6*u**5)
    totals = [distance, right_sign * distance, distance] + [math.radians(angle_deg)] * 3
    names = ["forward_x", "right_y", "up_z", "rotate_x", "rotate_y", "rotate_z"]
    forward = np.concatenate([weights[:, None] * np.eye(6)[axis] * total
                              for axis, total in enumerate(totals)])
    actions = np.concatenate([forward, -forward[::-1]])
    phases = names + ["undo_" + name for name in reversed(names)]
    return actions, [name for name in phases for _ in range(n)]


def decode_action(msg):
    dims = msg.layout.dim
    if (msg.layout.data_offset != 0 or len(dims) != 1 or dims[0].label != LABEL
            or dims[0].size != 6 or dims[0].stride != 6):
        raise ValueError("Unexpected action layout/contract")
    action = np.asarray(msg.data, dtype=np.float64)
    if action.shape != (6,) or not np.isfinite(action).all():
        raise ValueError("Expected six finite numbers")
    if np.linalg.norm(action[:3]) > .05 or np.linalg.norm(action[3:]) > math.radians(30):
        raise ValueError("Increment exceeds experiment bounds")
    return action


def action_message(action):
    from std_msgs.msg import Float64MultiArray, MultiArrayDimension
    msg = Float64MultiArray()
    msg.layout.dim = [MultiArrayDimension(label=LABEL, size=6, stride=6)]
    msg.data = np.asarray(action, dtype=float).tolist()
    decode_action(msg)
    return msg


def writer_at(path, topic_types):
    import rosbag2_py
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="mcap"),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    for topic, msg_type in topic_types:
        writer.create_topic(rosbag2_py.TopicMetadata(
            id=0, name=topic, type=msg_type, serialization_format="cdr"))
    return writer


def generate(args):
    from rclpy.serialization import serialize_message
    actions, phases = trajectory(args.hz, args.seconds, args.distance, args.angle_deg, args.right_sign)
    initial = pose(args.initial_pose)
    args.output.mkdir(parents=True, exist_ok=False)
    writer = writer_at(args.output / "commands", [(ACTION_TOPIC, "std_msgs/msg/Float64MultiArray")])
    start = time.time_ns()
    rows, current = [], initial.copy()
    for index, (action, phase) in enumerate(zip(actions, phases)):
        # Each decision is issued at the start of its nominal 1/hz horizon.
        stamp = start + round(index * 1e9 / args.hz)
        current = apply(current, action)
        writer.write(ACTION_TOPIC, serialize_message(action_message(action)), stamp)
        rows.append(dict(index=index, phase=phase, bag_timestamp_ns=stamp,
                         horizon_s=1/args.hz, action=action.tolist(), target_pose=current.tolist()))
    del writer
    manifest = dict(contract=LABEL, frame="base_link", hz=args.hz,
                    segment_seconds=args.seconds, distance_m=args.distance,
                    angle_deg=args.angle_deg, right_sign=args.right_sign,
                    initial_pose=initial.tolist(), action_topic=ACTION_TOPIC,
                    nominal_duration_s=len(actions)/args.hz,
                    interpretation="increment from current pose; mock assumes perfect following",
                    hardware_executed=False, rows=rows)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(output=str(args.output), decisions=len(rows),
                          duration_s=manifest["nominal_duration_s"],
                          return_error=between(initial, current).tolist()), indent=2))


def verify(args):
    import rclpy
    from rclpy.serialization import serialize_message
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from geometry_msgs.msg import PoseStamped
    from std_msgs.msg import Float64MultiArray

    manifest = json.loads((args.dataset / "manifest.json").read_text())
    if manifest["contract"] != LABEL or manifest["action_topic"] != ACTION_TOPIC:
        raise ValueError("Incompatible bag manifest")
    rows = manifest["rows"]
    args.output.mkdir(parents=True, exist_ok=False)
    writer = writer_at(args.output / "received", [
        (ACTION_TOPIC, "std_msgs/msg/Float64MultiArray"),
        (TARGET_TOPIC, "geometry_msgs/msg/PoseStamped")])
    rclpy.init()
    node = rclpy.create_node("omi_eef_action_mock_controller")
    qos = QoSProfile(depth=1000, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.VOLATILE)
    publisher = node.create_publisher(PoseStamped, TARGET_TOPIC, qos)
    current = pose(manifest["initial_pose"])
    arrivals, errors, targets = [], [], []

    def receive(msg):
        nonlocal current
        index = len(arrivals)
        arrivals.append(time.monotonic())
        stamp = node.get_clock().now().nanoseconds
        writer.write(ACTION_TOPIC, serialize_message(msg), stamp)
        if errors:
            return  # Latch failure; do not integrate further commands.
        try:
            delta = decode_action(msg)
            if index >= len(rows) or not np.allclose(delta, rows[index]["action"], rtol=0, atol=1e-14):
                raise ValueError(f"Missing, reordered, extra or altered decision at {index}")
            current = apply(current, delta)
            target = PoseStamped()
            target.header.frame_id = "base_link"
            target.header.stamp = node.get_clock().now().to_msg()
            target.pose.position.x, target.pose.position.y, target.pose.position.z = current[:3].tolist()
            (target.pose.orientation.x, target.pose.orientation.y,
             target.pose.orientation.z, target.pose.orientation.w) = current[3:].tolist()
            publisher.publish(target)
            writer.write(TARGET_TOPIC, serialize_message(target), stamp)
            targets.append(current.tolist())
        except ValueError as exc:
            errors.append(str(exc))

    subscription = node.create_subscription(Float64MultiArray, ACTION_TOPIC, receive, qos)
    process = None
    try:
        with (args.output / "player.log").open("w") as log:
            process = subprocess.Popen([
                "ros2", "bag", "play", str(args.dataset / "commands"),
                "--delay", "2", "--disable-keyboard-controls"], stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + manifest["nominal_duration_s"] + 20
            finished_at = None
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.05)
                if process.poll() is not None:
                    if finished_at is None:
                        finished_at = time.monotonic()
                    if time.monotonic() - finished_at >= 1.:
                        break
            if process.poll() is None:
                errors.append("Bag player timeout")
                process.terminate()
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait()
            if returncode:
                errors.append(f"Bag player exit code {returncode}")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()
        del writer
    if len(arrivals) != len(rows) or len(targets) != len(rows):
        errors.append(f"Expected {len(rows)} decisions/targets; got {len(arrivals)}/{len(targets)}")
    max_target_error = None
    if len(targets) == len(rows):
        max_target_error = float(np.max(np.abs(np.asarray(targets) - np.array([r["target_pose"] for r in rows]))))
        if max_target_error > 1e-10:
            errors.append("Target trajectory mismatch")
    endpoint_error = between(manifest["initial_pose"], current)
    if np.linalg.norm(endpoint_error) > 1e-10:
        errors.append("Did not return to initial pose")
    intervals = np.diff(arrivals)
    # Delivery timing is measured, but this test makes no real-time or hardware claim.
    report = dict(passed=not errors, errors=errors, expected=len(rows), received=len(arrivals),
                  generated_targets=len(targets), max_target_component_error=max_target_error,
                  endpoint_error=endpoint_error.tolist(), hardware_executed=False,
                  simulated_feedback="perfect following; current pose becomes target immediately",
                  arrival_interval_s=(dict(min=float(intervals.min()), median=float(np.median(intervals)),
                                           max=float(intervals.max())) if len(intervals) else None),
                  received_span_s=arrivals[-1]-arrivals[0] if len(arrivals) > 1 else 0.)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Write planned Float64MultiArray rosbag")
    gen.add_argument("--output", type=Path, required=True)
    gen.add_argument("--hz", type=float, default=10.)
    gen.add_argument("--seconds", type=float, default=2.)
    gen.add_argument("--distance", type=float, default=.05)
    gen.add_argument("--angle-deg", type=float, default=10.)
    gen.add_argument("--right-sign", type=int, choices=(-1, 1), default=-1)
    gen.add_argument("--initial-pose", nargs=7, type=float, default=IDENTITY,
                     metavar=("X", "Y", "Z", "QX", "QY", "QZ", "QW"))
    gen.set_defaults(run=generate)
    check = sub.add_parser("verify", help="Replay into isolated mock controller; record receipts and targets")
    check.add_argument("--dataset", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.set_defaults(run=verify)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
