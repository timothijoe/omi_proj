"""One sensor-only entry point; subprocess groups are always reaped on exit."""

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .config import camera_command, load_config, positive, sensor_topics, replay_topics
from .tactile_grid import MODES


def environment(config):
    env = os.environ.copy()
    discovery = env.get("OMI_SENSOR_DISCOVERY_RANGE", "LOCALHOST")
    if discovery not in ("LOCALHOST", "SUBNET"):
        raise ValueError("OMI_SENSOR_DISCOVERY_RANGE must be LOCALHOST or SUBNET")
    env.update(ROS_DOMAIN_ID=str(config["domain_id"]),
               ROS_LOCALHOST_ONLY="0" if discovery == "SUBNET" else "1",
               ROS_AUTOMATIC_DISCOVERY_RANGE=discovery, RMW_FASTRTPS_PUBLICATION_MODE="ASYNCHRONOUS")
    return env


def supervise(commands, env, duration=None, *, shutdown_grace=10):
    children = []
    previous = {}
    started = time.monotonic()

    def stop(signum, frame):
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        for cmd in commands:
            children.append(subprocess.Popen(cmd, env=env, start_new_session=True))
        while True:
            for child in children:
                code = child.poll()
                if code is not None:
                    return code
            if duration is not None and time.monotonic() - started >= duration:
                return 0
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 130
    finally:
        # Repeated Ctrl+C must not interrupt child cleanup/recording flush.
        for sig in previous:signal.signal(sig, signal.SIG_IGN)
        # SIGINT lets rosbag flush its index. Escalate only after a bounded grace period.
        for sig, timeout in ((signal.SIGINT, shutdown_grace), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            for child in children:
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + timeout
            for child in children:
                try:
                    child.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
            if all(c.poll() is not None for c in children):
                break
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def inventory(config):
    packages = subprocess.run(["dpkg-query", "-W", "-f=${Package}=${Version}\n", "ros-*-realsense2*", "ros-*-rosbag2*"],
                              capture_output=True, text=True, check=False)
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return {"schema_version": 1, "config": config, "created_ns": time.time_ns(),
            "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
            "ros_distro": os.environ.get("ROS_DISTRO", "unsourced"), "packages": packages.stdout.splitlines(),
            "topics": sensor_topics(config), "omi_sensors_version": "0.1.0", "omi_source_sha256": digest.hexdigest(),
            "timestamp_contract": "tactile host receive time; RealSense driver header; not hardware synchronized"}


def recording_report(output, topics):
    import yaml
    metadata = output / "bag" / "metadata.yaml"
    counts = {}
    if metadata.is_file():
        info = yaml.safe_load(metadata.read_text())["rosbag2_bagfile_information"]
        counts = {item["topic_metadata"]["name"]: item["message_count"] for item in info["topics_with_message_count"]}
    missing = [topic for topic in topics if counts.get(topic, 0) == 0]
    report = {"counts": counts, "missing_or_empty_topics": missing, "all_topics_present": not missing,
              "note": "Message counts only; not a synchronization or calibration validation"}
    (output / "recording_report.json").write_text(json.dumps(report, indent=2))
    if missing:
        print("Warning: missing/empty recorded topics: " + ", ".join(missing), file=sys.stderr)
    return report


@contextmanager
def playback_source(bag):
    """File-compressed legacy bags are decompressed in owned scratch, never in source."""
    import yaml
    bag = Path(bag).resolve()
    metadata = yaml.safe_load((bag / "metadata.yaml").read_text())
    info = metadata["rosbag2_bagfile_information"]
    mode = info.get("compression_mode", "")
    paths = info["relative_file_paths"]
    for relative in paths:
        source = (bag / relative).resolve()
        if not source.is_relative_to(bag) or not source.is_file():
            raise ValueError("bag file missing or outside bag directory: " + relative)
    if mode != "file":
        yield bag, info
        return
    if info.get("compression_format") != "zstd":
        raise ValueError("only zstd file compression is supported")
    with tempfile.TemporaryDirectory(prefix="omi-bag-") as temp:
        dest = Path(temp)
        mapping = {}
        for index, relative in enumerate(paths):
            name = "%04d_" % index + Path(relative).name.removesuffix(".zstd")
            subprocess.run(["zstd", "-d", "-o", str(dest / name), "--", str(bag / relative)], check=True)
            mapping[relative] = name
        info["relative_file_paths"] = [mapping[p] for p in paths]
        for entry in info.get("files", []):
            entry["path"] = mapping[entry["path"]]
        info["compression_mode"], info["compression_format"] = "", ""
        (dest / "metadata.yaml").write_text(yaml.safe_dump(metadata))
        yield dest, info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "plan", "live"):
        command_parser = sub.add_parser(name)
        if name == 'live':
            command_parser.add_argument('--tactile-mode', choices=MODES, default='full')
            command_parser.add_argument('--publish-raw', action='store_true')
    fake = sub.add_parser("fake")
    fake.add_argument("--duration", type=positive)
    fake.add_argument('--tactile-mode', choices=MODES, default='full')
    fake.add_argument('--publish-raw', action='store_true')
    dashboard = sub.add_parser("dashboard", help="subscribe to SDK-native fields; publish a human-view RGB dashboard")
    dashboard.add_argument("--rate", type=positive, default=10.0)
    dashboard.add_argument("--stale-seconds", type=positive, default=0.5)
    tactile = sub.add_parser("tactile", help=argparse.SUPPRESS)
    tactile.add_argument("side", choices=("a", "b"))
    tactile.add_argument('--tactile-mode', choices=MODES, default='full')
    tactile.add_argument('--publish-raw', action='store_true')
    record = sub.add_parser("record", help="record already-running sensors; output must not exist")
    record.add_argument("output", type=Path)
    record.add_argument("--duration", type=positive)
    replay = sub.add_parser("replay")
    replay.add_argument("bag", type=Path)
    replay.add_argument("--rate", type=positive, default=1.0)
    replay.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        commands = []
        if config["realsense"]["enabled"]:
            commands.append(camera_command(config))
        if config["tactile"]["enabled"]:
            mode_args = [] if getattr(args, 'tactile_mode', 'full') == 'full' else ['--tactile-mode', args.tactile_mode]
            if getattr(args, 'publish_raw', False):
                mode_args += ['--publish-raw']
            commands += [[sys.executable, "-m", "omi_sensors.cli", "--config", str(args.config.resolve()), "tactile", side, *mode_args]
                         for side in ("a", "b")]
        if args.command == "plan":
            print(json.dumps({"environment": {k: v for k, v in environment(config).items() if k.startswith("ROS_")},
                              "live_commands": commands, "record_topics": sensor_topics(config)}, indent=2))
            return 0
        if args.command == "doctor":
            from .tactile import sdk_check
            checks = {name: importlib.util.find_spec(name) is not None for name in ("rclpy", "sensor_msgs", "numpy", "yaml")}
            checks["ros2"] = shutil.which("ros2") is not None
            if config["realsense"]["enabled"]:
                checks["realsense2_camera"] = bool(checks["ros2"] and subprocess.run(
                    ["ros2", "pkg", "prefix", "realsense2_camera"], capture_output=True).returncode == 0)
            if config["tactile"]["enabled"]:
                try:
                    sdk_check(config["tactile"])
                    checks["sdk_path_and_python"] = True
                except RuntimeError as exc:
                    checks["sdk_path_and_python"] = False
                    print(str(exc), file=sys.stderr)
                checks["tactile_addresses"] = bool(config["tactile"]["host"] and config["tactile"]["pc_host"])
            print(json.dumps({"checks": checks, "note": "No hardware opened; SDK import/ABI and devices still need live acceptance",
                              "inventory": inventory(config)}, indent=2))
            return 0 if all(checks.values()) else 1
        if args.command == "dashboard":
            os.environ.update(environment(config))
            from .dashboard import run
            run(config, rate=args.rate, stale_s=args.stale_seconds)
            return 0
        if args.command in ("fake", "tactile"):
            os.environ.update(environment(config))
            from .node import run
            run(config, side=getattr(args, "side", None), fake=args.command == "fake", duration=getattr(args, "duration", None),
                tactile_mode=args.tactile_mode, publish_raw=args.publish_raw)
            return 0
        if args.command == "live":
            if not commands:
                raise ValueError("no sensors enabled")
            if config["tactile"]["enabled"]:
                from .tactile import sdk_check
                sdk_check(config["tactile"])
                if not config["tactile"]["host"] or not config["tactile"]["pc_host"]:
                    raise ValueError("set tactile host and pc_host before live")
            return supervise(commands, environment(config))
        if args.command == "record":
            topics = sensor_topics(config)
            if not topics:
                raise ValueError("no enabled sensor topics")
            # Exclusive parent session directory makes accidental overwrite impossible.
            args.output.mkdir(parents=True, exist_ok=False)
            (args.output / "session.json").write_text(json.dumps(inventory(config), indent=2))
            cmd = ["ros2", "bag", "record", "--storage", "sqlite3", "-o", str(args.output / "bag"), *topics]
            code = supervise([cmd], environment(config), args.duration)
            report = recording_report(args.output, topics)
            return 2 if code == 0 and not report["all_topics_present"] else code
        if args.command == "replay":
            with playback_source(args.bag) as (bag, info):
                existing = {item["topic_metadata"]["name"] for item in info["topics_with_message_count"]}
                topics = replay_topics(config, existing)
                if not topics:
                    raise ValueError("bag has no allowed sensor topics")
                cmd = ["ros2", "bag", "play", str(bag), "--rate", str(args.rate), "--clock", "--topics", *topics]
                if args.loop:
                    cmd.append("--loop")
                print("Replaying only: " + ", ".join(topics), flush=True)
                return supervise([cmd], environment(config))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print("omi-sensors: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
