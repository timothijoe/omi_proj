"""Versioned causal BC observation contract and read-only MCAP dataset export."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, deque
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

import numpy as np

from omi_hil_rl.real.observation import ObservationConfig, _crop_square_resize_nearest
from omi_hil_rl.real.ros_topics import decode_image_message, wrench_value

VERSION = "bag-bc-v1"
TOPICS = {"/camera/camera/color/image_raw": "rgb", "/tj/info/joint_feedback": "q"}
TOPICS.update({f"/tj/dm_sensor/{s}_{k}": f"{s}_{k}"
               for s in "ab" for k in ("deformation", "shear", "depth", "force")})
COMMAND = "/tj/control/joint_cmd_A"
KEYS = tuple(TOPICS.values())
ARRAYS = ("rgb", "tactile", "state")
CONTRACT = dict(version=VERSION, sample_hz=10, max_age_ns=250_000_000,
                label_horizon_ns=100_000_000, label_tolerance_ns=50_000_000,
                rgb_roi=[.507, .426, .40], rgb_shape=[3, 128, 128],
                tactile_shape=[10, 16, 24], state_shape=[19],
                tactile_order=[s+"_"+c for s in "ab" for c in ("def_x", "def_y", "shear_x", "shear_y", "depth")],
                state_order="q_left_7,a_wrench_Fxyz_Txyz,b_wrench_Fxyz_Txyz",
                action="assumed_left_absolute_joint_target_radians_7",
                preprocessing="camera_nearest_ROI; tactile_block_mean_18x16; raw_wrench",
                deployment="shadow_only; action semantics and hardware not verified")


def stamp(msg):
    value = int(msg.header.stamp.sec)*10**9 + int(msg.header.stamp.nanosec)
    if value <= 0:
        raise ValueError("Missing positive source header")
    return value


def pool_field(value):
    value = np.asarray(value, dtype=np.float32)
    if value.shape[:2] != (288, 384) or value.ndim not in (2, 3):
        raise ValueError("Expected 288x384 tactile field")
    if value.ndim == 2:
        value = value[..., None]
    return value.reshape(16, 18, 24, 16, value.shape[2]).mean(axis=(1, 3)).transpose(2, 0, 1)


def decode(key, message):
    if key == "q":
        value = np.asarray(message.arm_positions, dtype=np.float32)
        if value.shape != (14,):
            raise ValueError("Expected fourteen feedback positions")
        value = value[:7].copy()
    elif key.endswith("force"):
        value = wrench_value(message)
    else:
        value = decode_image_message(message)
        if not np.isfinite(value).all():
            raise ValueError("Nonfinite image/field")
        if key == "rgb":
            value = _crop_square_resize_nearest(value, ObservationConfig().external_rgb_roi, (128, 128))[0].transpose(2, 0, 1).copy()
        else:
            shape = (288, 384) if key.endswith("depth") else (288, 384, 2)
            if value.shape != shape:
                raise ValueError("Wrong tactile channel count")
            value = pool_field(value)
    if not np.isfinite(value).all():
        raise ValueError("Nonfinite observation")
    return stamp(message), value


class NotReady(ValueError):
    pass


class ObservationBuffer:
    """Bounded preprocessed histories; reference chooses source <= t, never future."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.data = {k: deque(maxlen=128) for k in KEYS}

    def add(self, key, timestamp, value):
        if timestamp <= 0 or not np.isfinite(value).all():
            raise ValueError("Invalid observation")
        items = self.data[key]
        if items and timestamp < items[-1][0]:
            raise ValueError("Backward source header; explicit replay reset required")
        if items and timestamp == items[-1][0]:
            items.pop()
        items.append((int(timestamp), value))

    def at(self, reference, expected=None):
        selected = {}
        for key, items in self.data.items():
            wanted = None if expected is None else expected[key]
            entry = next((x for x in reversed(items) if x[0] <= reference and (wanted is None or x[0] == wanted)), None)
            if entry is None:
                raise NotReady("missing:"+key)
            if reference-entry[0] > CONTRACT["max_age_ns"]:
                raise NotReady("stale:"+key)
            selected[key] = entry
        values = {k: v[1] for k, v in selected.items()}
        tactile = np.concatenate([values[s+"_"+k] for s in "ab" for k in ("deformation", "shear", "depth")])
        state = np.concatenate([values["q"], values["a_force"], values["b_force"]]).astype(np.float32)
        return dict(rgb=values["rgb"], tactile=tactile, state=state), {k: v[0] for k, v in selected.items()}


def digest(observation):
    h = hashlib.sha256()
    for key in ARRAYS:
        h.update(np.ascontiguousarray(observation[key]).tobytes())
    return h.hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def open_bag(source, scratch):
    """Accept one bag directory or a ZIP containing exactly one metadata file."""
    import yaml
    source = Path(source).resolve()
    with tempfile.TemporaryDirectory(prefix="bc-read-", dir=scratch) as tmp:
        tmp = Path(tmp)
        if source.is_file():
            with zipfile.ZipFile(source) as archive:
                metadata = [n for n in archive.namelist() if n == "metadata.yaml" or n.endswith("/metadata.yaml")]
                if len(metadata) != 1:
                    raise ValueError("Expected one bag in ZIP")
                meta_bytes = archive.read(metadata[0])
                info = yaml.safe_load(meta_bytes)["rosbag2_bagfile_information"]
                base = Path(metadata[0]).parent
                sources = []
                for i, name in enumerate(info["relative_file_paths"]):
                    if Path(name).is_absolute() or ".." in Path(name).parts:
                        raise ValueError("Unsafe bag member path")
                    path = tmp/f"source-{i}"
                    with archive.open(str(base/name)) as src, path.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
                    sources.append(path)
                provenance = dict(path=str(source), sha256=sha256(source))
        else:
            meta_bytes = (source/"metadata.yaml").read_bytes()
            info = yaml.safe_load(meta_bytes)["rosbag2_bagfile_information"]
            sources = [(source/n).resolve() for n in info["relative_file_paths"]]
            if any(not p.is_relative_to(source) for p in sources):
                raise ValueError("Unsafe bag file path")
            provenance = dict(path=str(source), metadata_sha256=hashlib.sha256(meta_bytes).hexdigest(),
                              files=[dict(name=p.name, sha256=sha256(p)) for p in sources])
        mode = info.get("compression_mode", "").lower()
        if info["storage_identifier"] != "mcap" or mode not in ("", "none", "file"):
            raise ValueError("Only MCAP uncompressed or file-zstd supported")
        if mode == "file" and info.get("compression_format") != "zstd":
            raise ValueError("Unsupported compression")
        paths = []
        for i, path in enumerate(sources):
            if mode == "file":
                target = tmp/f"input-{i}.mcap"
                with target.open("xb") as dst:
                    subprocess.run(["zstd", "-dc", "--", str(path)], stdout=dst, check=True)
                path = target
            paths.append(path)
        yield info, paths, provenance


def reader(path):
    import rosbag2_py
    result = rosbag2_py.SequentialReader()
    result.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="mcap"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    return result


def export(source, output, *, accept_assumptions=False):
    if not accept_assumptions:
        raise ValueError("Explicit --assume-absolute-radian-targets required; physical semantics are unverified")
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Refuse to overwrite dataset: "+str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bc-export-", dir=output.parent) as work:
        work = Path(work)
        build = work/"dataset"
        build.mkdir()
        with open_bag(source, work) as (info, paths, provenance):
            start = int(info["starting_time"]["nanoseconds_since_epoch"])
            end = start+int(info["duration"]["nanoseconds"])
            if end <= start:
                raise ValueError("Empty duration")
            buf, commands, samples, refs = ObservationBuffer(), [], [], []
            counts, dropped = Counter(), Counter()
            episode_hash = hashlib.sha256()
            ref, previous = start, start
            writer = rosbag2_py.SequentialWriter()
            writer.open(rosbag2_py.StorageOptions(uri=str(build/"observations"), storage_id="mcap"), rosbag2_py.ConverterOptions("cdr", "cdr"))
            registered = set()

            def capture(t):
                row = dict(reference_ns=t)
                try:
                    observation, stamps = buf.at(t)
                    samples.append((t, observation, stamps))
                    row.update(valid=True, source_stamps=stamps, observation_sha256=digest(observation))
                except NotReady as exc:
                    row.update(valid=False, reason=str(exc))
                    dropped[str(exc)] += 1
                refs.append(row)

            for path in paths:
                rd = reader(path)
                types = {t.name: t for t in rd.get_all_topics_and_types() if t.name in TOPICS or t.name == COMMAND}
                classes = {name: get_message(meta.type) for name, meta in types.items()}
                if not classes:
                    raise ValueError("Missing observation topics")
                rd.set_filter(rosbag2_py.StorageFilter(topics=list(classes)))
                for name, meta in types.items():
                    if name != COMMAND and name not in registered:
                        writer.create_topic(meta)
                        registered.add(name)
                while rd.has_next():
                    topic, data, received = rd.read_next()
                    if received < previous:
                        raise ValueError("Bag reception time goes backwards")
                    previous = received
                    episode_hash.update(topic.encode()+b"\0"+str(received).encode()+b"\0"+data)
                    while ref < received:
                        capture(ref)
                        ref += 100_000_000
                    msg = deserialize_message(data, classes[topic])
                    timestamp = stamp(msg)
                    if timestamp > received:
                        raise ValueError("Header clock later than reception; investigate clocks")
                    counts[topic] += 1
                    if topic == COMMAND:
                        q = np.asarray(msg.positions, dtype=np.float32)
                        if q.shape != (7,) or not np.isfinite(q).all() or np.any(np.abs(q) > 2*np.pi):
                            raise ValueError("Action invalid or inconsistent with assumed radians")
                        if commands and timestamp < commands[-1][0]:
                            raise ValueError("Command timestamp backwards")
                        commands.append((timestamp, q))
                    else:
                        key = TOPICS[topic]
                        buf.add(key, *decode(key, msg))
                        writer.write(topic, data, received)
                del rd
            while ref <= end:
                capture(ref)
                ref += 100_000_000
            del writer
            if set(TOPICS) != registered or not commands:
                raise ValueError("Required observations/commands missing")
            command_stamps = [x[0] for x in commands]
            rows, labels, label_stamps = [], [], []
            for t, observation, stamps in samples:
                desired = t+CONTRACT["label_horizon_ns"]
                i = bisect_left(command_stamps, desired)
                if i == len(commands) or command_stamps[i]-desired > CONTRACT["label_tolerance_ns"]:
                    dropped["missing_future_label"] += 1
                    continue
                rows.append((t, observation, stamps))
                labels.append(commands[i][1])
                label_stamps.append(commands[i][0])
            if len(rows) < 2:
                raise ValueError("Too few valid samples")
            arrays = {k: np.stack([r[1][k] for r in rows]) for k in ARRAYS}
            arrays.update(action=np.stack(labels), reference_ns=np.array([r[0] for r in rows], dtype=np.int64),
                          label_ns=np.array(label_stamps, dtype=np.int64),
                          source_ns=np.array([[r[2][k] for k in KEYS] for r in rows], dtype=np.int64))
            np.savez_compressed(build/"samples.npz", **arrays)
            (build/"references.json").write_text(json.dumps(refs))
            report = dict(contract=CONTRACT, source=provenance, episode_id=episode_hash.hexdigest(),
                          interpretation="one input bag = one episode; outcome unknown, not certified successful demonstration",
                          start_ns=start, end_ns=end, input_counts=dict(counts), dropped=dict(dropped),
                          samples=len(rows), reference_count=len(refs), source_order=list(KEYS),
                          hold_current_q_rmse_rad=float(np.sqrt(np.mean((arrays["action"]-arrays["state"][:,:7])**2))),
                          maximum_abs_target_rad=float(np.max(np.abs(arrays["action"]))),
                          maximum_target_minus_feedback_rad=float(np.max(np.abs(arrays["action"]-arrays["state"][:,:7]))),
                          samples_sha256=sha256(build/"samples.npz"))
            (build/"manifest.json").write_text(json.dumps(report, indent=2))
        build.rename(output)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--assume-absolute-radian-targets", action="store_true")
    a = p.parse_args()
    print(json.dumps(export(a.source, a.output, accept_assumptions=a.assume_absolute_radian_targets), indent=2))


if __name__ == "__main__":
    main()
