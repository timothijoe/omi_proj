"""Read live Tianji ROS topics and emit network-ready observations.

This command creates subscriptions only. It has no publisher and cannot command
the robot.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from .observation import ObservationConfig, ObservationNotReady
from .ros_topics import TianjiRosObservationNode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup-seconds", type=float, default=1.0)
    parser.add_argument("--print-period", type=float, default=1.0)
    parser.add_argument("--max-age-s", type=float, default=0.25)
    parser.add_argument("--torch", action="store_true", help="also validate conversion to batched Torch tensors")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    if args.warmup_seconds < 0 or args.print_period <= 0:
        parser.error("warmup-seconds must be nonnegative and print-period must be positive")

    interface = TianjiRosObservationNode(ObservationConfig(max_age_s=args.max_age_s))
    started = time.monotonic()
    last_print = 0.0
    baseline_captured = False
    try:
        while True:
            interface.spin_once(timeout_s=0.05)
            now = time.monotonic()
            timestamp_ns = interface.now_ns()
            if not baseline_captured and now - started >= args.warmup_seconds:
                try:
                    interface.builder.validate_sensor_set(timestamp_ns)
                    interface.builder.capture_grasp_baseline(timestamp_ns)
                except ObservationNotReady:
                    continue
                baseline_captured = True
                print(f"captured grasp baseline at {timestamp_ns}", flush=True)
            if not baseline_captured or now - last_print < args.print_period:
                continue
            try:
                observation = interface.latest_observation()
            except ObservationNotReady as exc:
                print(f"observation rejected: {exc}", flush=True)
                last_print = now
                continue
            report = {
                "sensor_age_s": np.round(observation["sensor_age_s"], 4).tolist(),
                "valid": observation["sensor_valid"].tolist(),
                "state_shape": list(observation["state"].shape),
                "external_rgb_shape": list(observation["external_rgb"].shape),
                "wrist_rgb_shape": list(observation["wrist_rgb"].shape),
                "tactile_raw_shape": list(observation["tactile_raw"].shape),
                "tactile_depth_shape": list(observation["tactile_depth_delta"].shape),
            }
            if args.torch:
                tensors = interface.latest_torch_observation(device=args.device)
                report["torch_shapes"] = {key: list(value.shape) for key, value in tensors.items()}
            print(json.dumps(report), flush=True)
            last_print = now
    except KeyboardInterrupt:
        pass
    finally:
        interface.close()


if __name__ == "__main__":
    main()
