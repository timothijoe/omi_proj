"""Reward-independent human demonstrations; no learner or policy required."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import numpy as np

from .config import HILConfig, load_config
from .demo_bag import SAMPLE_TOPIC, encode_sample
from .environment import FakeTransport, RealHILEnv, InteractionUnavailable, EpisodeTimeout, EpisodeSuccess
from .exchange import atomic_json, owner_lock
from omi_hil_rl.training.transition_replay import _spaces, _array

DEMO_VERSION = "omi-human-demo-v1"
COMMAND_TOPICS = ("/omi/action/decision", "/omi/action/manual_decision",
                  "/omi/action/command_trace", "/omi/action/receipt", "/omi/demo/event", SAMPLE_TOPIC)


def recording_topics(observation_topics, *, command_topic="/omi/action/decision", extra_topics=()):
    return sorted(set([*observation_topics, command_topic, *COMMAND_TOPICS,
        "/tj/info/joint_feedback", "/omi/wrist/color/image_raw", "/omi/wrist/color/image_roi",
        "/omi/wrist/color/image_raw/record", "/omi/wrist/color/image_roi/record",
        "/omi/wrist/metadata", "/omi/wrist/status",
        *[f"/omi/tactile_grid24x16/{side}/{kind}" for side in 'ab'
          for kind in ('wrench', 'metadata', 'status')], *extra_topics]))


def save_npz(path, arrays):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(path)


def validate_command_label(contract, action, metadata):
    """Join the physical command, its training label and receipt by command ID."""
    if contract["config"]["transport"] == "fake":
        return
    from omi_hil_rl.real.sdk_action import output_action
    try:
        audit = metadata["command_audit"]
        trace, receipt = audit["command_trace"], audit["receipt"]
        command_id = audit["command_id"]
        stamp = metadata["observation_time_ns"]
        if not (command_id and command_id == trace["command_id"] == receipt["command_id"]):
            raise ValueError("command ID mismatch")
        if not receipt["accepted"] or not receipt["finished"] or trace["action_source"] != "human" or not trace["label_candidate"]:
            raise ValueError("command was not adopted human input")
        if trace["command_topic"] != audit["command_topic"] or trace["observation_reference_ns"] != stamp:
            raise ValueError("command topic/observation anchor mismatch")
        if not stamp <= trace["command_send_ns"] <= audit["command_send_ns"] < metadata["next_observation_time_ns"]:
            raise ValueError("noncausal command label")
        if trace["output_convention"] != contract["config"]["sdk_convention"] or trace["action_contract"] != contract["action_contract"]:
            raise ValueError("command conversion contract mismatch")
        if not np.array_equal(np.asarray(trace["normalized_action"], np.float32), action):
            raise ValueError("normalized command label mismatch")
        physical = np.asarray(trace["action_m_rad"], np.float64)
        expected = np.asarray(action, np.float64) * np.asarray(contract["physical_action_scale"], np.float64)
        if physical.shape != (6,) or not np.allclose(physical, expected, atol=1e-9, rtol=1e-6):
            raise ValueError("physical command label mismatch")
        wire = output_action(physical, trace["output_convention"])
        for actual in (trace["wire_action"], audit["wire_action"], receipt["wire_action"]):
            if np.asarray(actual).shape != (6,) or not np.allclose(wire, actual, atol=1e-9, rtol=1e-9):
                raise ValueError("wire command label mismatch")
    except (KeyError, TypeError) as exc:
        raise ValueError("missing command label/receipt evidence") from exc


class DemoEpisode:
    def __init__(self, directory, episode, contract, *, raw_bag=None, synthetic=False):
        self.directory = Path(directory) / "episodes" / episode
        self.directory.mkdir(parents=True, exist_ok=False)
        self.contract, self.episode, self.count = contract, episode, 0
        self.spaces, self.action_space = _spaces(contract)
        self.last_stamp = None
        self.manifest = dict(version=DEMO_VERSION, episode=episode, contract=contract, raw_bag=raw_bag,
                             synthetic=synthetic, reward_available=False, action_semantics="accepted_command")
        atomic_json(self.directory / "staging.json", self.manifest)

    def append(self, observation, next_observation, info, current_audit=None):
        if info["action_source"] != "human" or not info["valid_transition"]:
            raise ValueError("demo requires valid adopted human commands")
        if info["episode"] != self.episode or info["step"] != self.count:
            raise ValueError("demo episode/step mismatch")
        current, nxt = int(info["observation_time_ns"]), int(info["next_observation_time_ns"])
        if not 0 < current < nxt or (self.last_stamp is not None and current != self.last_stamp):
            raise ValueError("demo chronology mismatch")
        arrays = {}
        for name, values in (("observation", observation), ("next_observation", next_observation)):
            if set(values) != set(self.spaces.spaces):
                raise ValueError("demo observation keys mismatch")
            for key, space in self.spaces.spaces.items():
                arrays[name + "__" + key] = _array(values[key], space, name + "." + key)
            if not np.all(values["history_mask"]) or np.any(values["state"][:, :7]):
                raise ValueError("demo needs complete history with disabled joints")
        action = _array(info["executed_action"], self.action_space, "executed_action")
        metadata = dict(episode=self.episode, step=self.count, observation_time_ns=current,
            next_observation_time_ns=nxt, action_source="human", command_status=info["command_status"],
            events=info.get("events", []), event_times=info.get("event_times", {}),
            current_observation_audit=current_audit or {}, command_audit=info.get("command_audit", {}))
        validate_command_label(self.contract, action, metadata)
        physical = metadata["command_audit"].get("command_trace", {}).get("action_m_rad")
        physical = (action * np.asarray(self.contract["physical_action_scale"], np.float32)
                    if physical is None else np.asarray(physical, np.float32))
        arrays.update(executed_action=action,
            action_m_rad=physical,
            metadata=np.asarray(json.dumps(metadata, allow_nan=False)))
        save_npz(self.directory / f"{self.count:06d}.npz", arrays)
        self.count += 1
        self.last_stamp = nxt

    def finish(self, keep, outcome, *, valid=True, reason=None, started=None, deadline=None):
        if outcome not in ("success", "timeout", "unknown", "invalid"):
            raise ValueError("unknown operator outcome")
        if keep and (not valid or not self.count):
            raise ValueError("empty or invalid demo cannot be retained")
        manifest = dict(self.manifest, count=self.count, keep=bool(keep), valid=bool(valid),
                        operator_outcome=outcome, reason=reason, started_monotonic=started, deadline_monotonic=deadline)
        atomic_json(self.directory / "demo.json", manifest)
        return manifest


def read_demo_step(directory, index, manifest=None):
    directory = Path(directory)
    manifest = manifest or json.loads((directory / "demo.json").read_text())
    if manifest["version"] != DEMO_VERSION or not 0 <= index < manifest["count"]:
        raise ValueError("invalid demo version/index")
    with np.load(directory / f"{index:06d}.npz", allow_pickle=False) as archive:
        metadata = json.loads(str(archive["metadata"]))
        observation = {k.removeprefix("observation__"): archive[k].copy() for k in archive.files if k.startswith("observation__")}
        next_observation = {k.removeprefix("next_observation__"): archive[k].copy() for k in archive.files if k.startswith("next_observation__")}
        action = archive["executed_action"].copy()
        physical = archive["action_m_rad"].copy()
    if metadata["episode"] != manifest["episode"] or metadata["step"] != index or metadata["action_source"] != "human":
        raise ValueError("demo metadata mismatch")
    if not np.allclose(physical, action * np.asarray(manifest["contract"]["physical_action_scale"], np.float32), atol=1e-9, rtol=1e-6):
        raise ValueError("physical/normalized action mismatch")
    validate_command_label(manifest["contract"], action, metadata)
    return observation, next_observation, action, metadata


class SyntheticHuman(FakeTransport):
    """Scripted synthetic fixtures, distinctly marked; not real human evidence."""
    def __init__(self, config, success_step=8):
        super().__init__(config, success_step=success_step)
        self.episode_number = 0

    def reset_history(self):
        super().reset_history()
        self.episode_number += 1
        self.state[7] = .1 * self.episode_number
        self.state[-1] = 1.

    def interact(self, action, anchor_stamp, deadline):
        desired = np.array([.3 + .1 * self.state[7], -.2, .1, 0., 0., .15], np.float32)
        result = super().interact(self.config.physical_action(desired), anchor_stamp, deadline)
        result.source = "human"
        result.command_status = "synthetic_script_not_real_human"
        return result


class RawBag:
    """Separate rosbag process captures messages before model selection/rejection."""
    def __init__(self, directory, topics, *, all_topics=False):
        directory = Path(directory)
        self.directory = directory
        self.topics, self.all_topics = list(topics), all_topics
        self.path = directory / "raw"
        self.log = (directory / "rosbag.log").open("w")
        command = ["ros2", "bag", "record", "--storage", "sqlite3", "--output", str(self.path),
                   "--disable-keyboard-controls"]
        command += ["--all-topics"] if all_topics else ["--topics", *sorted(set(topics))]
        self.command = command
        try:
            self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            until = time.monotonic() + 15.
            while not list(self.path.glob("*.db3")):
                self.check()
                if time.monotonic() >= until:
                    raise RuntimeError("raw recorder startup timed out; see rosbag.log")
                time.sleep(.05)
        except BaseException:
            self.close()
            raise

    def check(self):
        if self.process.poll() is not None:
            raise InteractionUnavailable("raw recorder exited; see rosbag.log")

    def wait_subscriptions(self, node, baseline, timeout=15.):
        until = time.monotonic() + timeout
        while any(node.count_subscribers(topic) <= count for topic, count in baseline.items()):
            self.check()
            if time.monotonic() >= until:
                raise RuntimeError("raw recorder did not subscribe to active observation/command topics")
            time.sleep(.02)

    def close(self):
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        self.log.close()
        metadata_path = self.path / "metadata.yaml"
        coverage = dict(requested_topics=self.topics, all_topics=self.all_topics,
                        recorder_returncode=process.returncode if process else None, metadata_present=metadata_path.exists())
        if metadata_path.exists():
            import yaml
            metadata = yaml.safe_load(metadata_path.read_text())["rosbag2_bagfile_information"]
            counts = {row["topic_metadata"]["name"]: row["message_count"] for row in metadata["topics_with_message_count"]}
            coverage.update(message_counts=counts, requested_without_messages=[t for t in self.topics if not counts.get(t)])
        atomic_json(self.directory / "raw_recording.json", coverage)


def collect(directory, config, *, episodes=6, execute=False, gamepad="/dev/input/js0",
            raw_bag=True, all_topics=False, extra_topics=(), fake_steps=8, transport=None):
    if episodes < 1 or fake_steps < 1:
        raise ValueError("positive episodes/steps required")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    recorder = None
    env = None
    event_pub = None
    sample_pub = None
    results = []
    with owner_lock(directory, "demo"):
        with (directory / "events.jsonl").open("w") as events:
            def emit(kind, values):
                row = dict(kind=kind, monotonic_ns=time.monotonic_ns(), wall_time_ns=time.time_ns(), **values)
                if hasattr(transport, "node"):
                    row["ros_time_ns"] = transport.node.get_clock().now().nanoseconds
                events.write(json.dumps(row, allow_nan=False) + "\n")
                events.flush()
                if event_pub:
                    from std_msgs.msg import String
                    event_pub.publish(String(data=json.dumps(row, allow_nan=False)))
            try:
                if transport is None:
                    if config.transport == "fake":
                        transport = SyntheticHuman(config, success_step=fake_steps)
                    else:
                        from .ros_transport import RosTransport
                        from omi_hil_rl.training.eef_bc_grid import GridProfile
                        transport = RosTransport(config, GridProfile(config.wrist_camera).CONTRACT,
                            execute=execute, gamepad=gamepad, convention=config.sdk_convention)
                transport.human_only = True
                transport.allow_manual_reset = True
                transport.event_hook = emit
                env = RealHILEnv(transport, config)
                if config.transport == "ros":
                    from std_msgs.msg import String
                    event_pub = transport.node.create_publisher(String, "/omi/demo/event", 10)
                    sample_pub = transport.node.create_publisher(String, SAMPLE_TOPIC, 10)
                    if raw_bag:
                        topics = recording_topics(transport.runtime.topics, command_topic=transport.topic, extra_topics=extra_topics)
                        baseline = {topic: transport.node.count_subscribers(topic) for topic in topics
                                    if transport.node.count_publishers(topic) > 0}
                        recorder = RawBag(directory, topics, all_topics=all_topics)
                        recorder.wait_subscriptions(transport.node, baseline)
                        transport.health_check = recorder.check
                atomic_json(directory / "session.json", dict(version=DEMO_VERSION, config=asdict(config),
                    contract=config.replay_contract(), synthetic=config.transport == "fake", reward_available=False,
                    mode="preview" if config.transport == "ros" and not execute else "human_collection",
                    raw_bag="raw" if recorder else None, raw_recorder_command=recorder.command if recorder else None))
                emit("session_start", dict(config=asdict(config)))
                if config.transport == "ros" and not execute:
                    transport.reset_history()
                    for _ in range(episodes):
                        if recorder:
                            recorder.check()
                        obs, stamp = transport.observe(time.monotonic() + config.episode_seconds)
                        print(json.dumps(dict(preview=True, observation_time_ns=stamp, shapes={k:list(v.shape) for k,v in obs.items()})), flush=True)
                        time.sleep(.1)
                    return results
                for _ in range(episodes):
                    if recorder:
                        recorder.check()
                    emit("waiting_start", {})
                    try:
                        observation, reset_info = env.reset()
                    except InteractionUnavailable as exc:
                        emit("start_failed", dict(reason=str(exc)))
                        continue
                    episode = DemoEpisode(directory, reset_info["episode"], config.replay_contract(),
                        raw_bag="../../raw" if recorder else None, synthetic=config.transport == "fake")
                    emit("episode_start", reset_info)
                    audit = dict(getattr(transport, "latest_status", {}))
                    try:
                        while True:
                            if recorder:
                                recorder.check()
                            # No network is evaluated: only the adopted human action is used.
                            nxt, _, terminated, truncated, info = env.step(np.zeros(6, np.float32))
                            episode.append(observation, nxt, info, audit)
                            if sample_pub is not None:
                                sample_pub.publish(String(data=json.dumps(encode_sample(episode.episode, info["step"],
                                    episode.directory / f'{info["step"]:06d}.npz'))))
                            emit("transition", dict(episode=episode.episode, step=info["step"],
                                observation_time_ns=info["observation_time_ns"], next_observation_time_ns=info["next_observation_time_ns"],
                                action_m_rad=config.physical_action(info["executed_action"]).tolist(), command_audit=info["command_audit"]))
                            observation = nxt
                            audit = info["command_audit"].get("next_observation_status", {})
                            if terminated or truncated:
                                outcome = "success" if terminated else "timeout"
                                break
                    except EpisodeTimeout:
                        outcome = "timeout"  # original raw data is unchanged; no reward or fictitious action
                    except EpisodeSuccess:
                        outcome = "success"
                    except InteractionUnavailable as exc:
                        transport.stop()
                        result = episode.finish(False, "invalid", valid=False, reason=str(exc))
                        env.phase = "idle"
                        results.append(result)
                        emit("episode_end", result)
                        continue
                    keep = env.review() if episode.count else False
                    if not episode.count:
                        env.phase = "idle"
                    result = episode.finish(keep, outcome, started=reset_info["started"], deadline=reset_info["deadline"])
                    results.append(result)
                    emit("episode_end", result)
                    print(json.dumps(dict(episode=result["episode"], count=result["count"], keep=keep, outcome=outcome, reward_available=False)), flush=True)
                return results
            finally:
                try:
                    try:
                        if env:
                            env.transport.stop()  # stop before waiting for recorder acknowledgements
                        if recorder and event_pub is not None:
                            from rclpy.duration import Duration
                            for publisher in (sample_pub, event_pub):
                                publisher.wait_for_all_acked(Duration(seconds=2))
                    finally:
                        if env:
                            env.close()
                finally:
                    if recorder:
                        recorder.close()


def annotate(directory, *, outcome, version, success_step=None, note=""):
    """Versioned reward sidecar; preserves original observations/actions/markers."""
    directory = Path(directory)
    manifest = json.loads((directory / "demo.json").read_text())
    if not manifest["keep"] or not manifest["valid"] or manifest["count"] < 1:
        raise ValueError("annotations require a retained valid demo")
    if outcome not in ("success", "timeout", "failure"):
        raise ValueError("reward outcome must be success/timeout/failure")
    if not version or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in version):
        raise ValueError("version must be a safe nonempty identifier")
    count = manifest["count"]
    if outcome == "success":
        success_step = count - 1 if success_step is None else success_step
        if type(success_step) is not int or not 0 <= success_step < count:
            raise ValueError("success step outside retained demo")
        count = success_step + 1
    elif success_step is not None:
        raise ValueError("success_step only applies to success")
    rewards, terminated, truncated = [0.] * count, [False] * count, [False] * count
    if outcome == "success":
        rewards[-1], terminated[-1] = 1., True
    elif outcome == "timeout":
        truncated[-1] = True
    else:
        terminated[-1] = True
    path = directory / ("reward_" + version + ".json")
    # Exclusive creation prevents accidental replacement of an existing label version.
    value = dict(version=version, episode=manifest["episode"], outcome=outcome, valid_length=count,
                 rewards=rewards, terminated=terminated, truncated=truncated, note=note)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    capture = sub.add_parser("collect")
    capture.add_argument("--directory", type=Path, required=True)
    capture.add_argument("--config", type=Path)
    capture.add_argument("--episodes", type=int, default=6)
    capture.add_argument("--execute", action="store_true")
    capture.add_argument("--gamepad", default="/dev/input/js0")
    capture.add_argument("--no-raw-bag", action="store_true")
    capture.add_argument("--all-topics", action="store_true", help="record all discovered ROS topics instead of the observation list")
    capture.add_argument("--raw-topic", action="append", default=[])
    capture.add_argument("--fake-steps", type=int, default=8)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--directory", type=Path, required=True)
    label = sub.add_parser("annotate")
    label.add_argument("--episode", type=Path, required=True)
    label.add_argument("--outcome", choices=("success", "timeout", "failure"), required=True)
    label.add_argument("--version", required=True)
    label.add_argument("--success-step", type=int)
    label.add_argument("--note", default="")
    args = parser.parse_args()
    if args.operation == "collect":
        config = load_config(args.config) if args.config else HILConfig()
        if args.execute and config.transport != "ros":
            parser.error("--execute requires transport=ros")
        collect(args.directory, config, episodes=args.episodes, execute=args.execute, gamepad=args.gamepad,
            raw_bag=not args.no_raw_bag, all_topics=args.all_topics, extra_topics=args.raw_topic, fake_steps=args.fake_steps)
    elif args.operation == "inspect":
        manifests = [json.loads(p.read_text()) for p in sorted(args.directory.glob("episodes/*/demo.json"))]
        coverage_path = args.directory / "raw_recording.json"
        print(json.dumps(dict(episodes=len(manifests), retained=sum(m["keep"] for m in manifests),
            samples=sum(m["count"] for m in manifests if m["keep"]),
            incomplete_episodes=sum(not (p.parent / "demo.json").exists() for p in args.directory.glob("episodes/*/staging.json")),
            raw_recording=json.loads(coverage_path.read_text()) if coverage_path.exists() else None,
            details=[{k:m[k] for k in ("episode", "count", "keep", "valid", "operator_outcome", "synthetic")} for m in manifests]), indent=2))
    else:
        print(json.dumps(annotate(args.episode, outcome=args.outcome, version=args.version, success_step=args.success_step, note=args.note), indent=2))


if __name__ == "__main__":
    main()
