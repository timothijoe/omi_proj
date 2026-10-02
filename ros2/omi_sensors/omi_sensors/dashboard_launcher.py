"""Start only an SDK-native subscriber, optional synthetic source or safe bag replay."""

import argparse
from pathlib import Path
import sys

from .cli import environment, supervise
from .config import load_config, positive


def validate_bag(bag, config):
    import yaml
    info = yaml.safe_load((bag / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
    types = {v["topic_metadata"]["name"]: (v["topic_metadata"]["type"], v["message_count"]) for v in info["topics_with_message_count"]}
    required = {}
    if config["tactile"]["enabled"]:
        for side in ("a", "b"):
            for kind in ("raw", "infer", "deformation", "shear", "metadata"):
                required["/omi/tactile/%s/%s" % (side, kind)] = "std_msgs/msg/String" if kind == "metadata" else "sensor_msgs/msg/Image"
    if config["realsense"]["enabled"]:
        required.update({"/camera/camera/color/image_raw": "sensor_msgs/msg/Image", "/camera/camera/color/camera_info": "sensor_msgs/msg/CameraInfo"})
    missing = [topic for topic, kind in required.items() if topic not in types or types[topic][0] != kind or types[topic][1] <= 0]
    if missing:
        raise ValueError("Bag lacks SDK-native nonempty topics: %s. Legacy record010 uses view_observation_bag.sh; this viewer does not reconstruct fields." % ", ".join(missing))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fake", action="store_true", help="synthetic data only; never connect hardware")
    source.add_argument("--bag", type=Path, help="SDK-native bag directory, not the enclosing session directory")
    parser.add_argument("--no-rviz", action="store_true")
    parser.add_argument("--rate", type=positive, default=1.0, help="bag speed")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--display-rate", type=positive, default=10.0)
    parser.add_argument("--stale-seconds", type=positive, default=0.5)
    parser.add_argument("--duration", type=positive, help="optional bounded runtime for headless validation")
    parser.add_argument("--rviz-config", type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if config["domain_id"] == 87:
            print("Warning: domain 87 is also the legacy viewer default. Do not run native and legacy sources together in this domain.", file=sys.stderr)
        if not config["tactile"]["enabled"] and not config["realsense"]["enabled"]:
            raise ValueError("no sensor panels enabled")
        if args.loop and args.bag is None:
            raise ValueError("--loop requires --bag")
        if args.bag:
            validate_bag(args.bag, config)
        base = [sys.executable, "-m", "omi_sensors.cli", "--config", str(args.config.resolve())]
        commands = [base + ["dashboard", "--rate", str(args.display_rate), "--stale-seconds", str(args.stale_seconds)]]
        if args.fake:
            commands.append(base + ["fake"])
        elif args.bag:
            commands.append(base + ["replay", str(args.bag.resolve()), "--rate", str(args.rate)] + (["--loop"] if args.loop else []))
        if not args.no_rviz:
            if args.rviz_config is None:
                from ament_index_python.packages import get_package_share_directory
                args.rviz_config = Path(get_package_share_directory("omi_sensors")) / "config/sdk_dashboard.rviz"
            commands.append(["rviz2", "-d", str(args.rviz_config)])
        print("SDK-native viewer | localhost domain %s | %s | output /omi/sdk/dashboard" % (config["domain_id"], "SYNTHETIC" if args.fake else "BAG" if args.bag else "SUBSCRIBE ONLY"), flush=True)
        return supervise(commands, environment(config), args.duration)
    except (ValueError, OSError, KeyError) as exc:
        print("SDK dashboard: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
