"""Offline native-field bag dashboard; publishes visualization only, never commands.

Rendering is cached at 10 Hz in bag-receive order, retaining source-header ages.
This is a review tool, not a training-data synchronization/export pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .observation import ObservationConfig, _crop_square_resize_nearest, _resize_nearest
from .ros_topics import decode_image_message, wrench_value
from .tactile_vectors import render_vector_field

NS = "/omi/recorded"
TOPICS = {"/camera/camera/color/image_raw": "camera",
          "/tj/info/joint_feedback": "joints", "/tj/info/eef_left": "eef"}
TOPICS.update({f"/tj/dm_sensor/{s}_{k}": f"{s}_{k}"
               for s in "ab" for k in ("raw", "deformation", "shear", "depth", "force")})
VERSION = 2
WIDTH, HEIGHT = 1536, 1170


def source_stamp(msg):
    value = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
    if value <= 0:
        raise ValueError("Missing source timestamp")
    return value


def decode(key, msg):
    if key == "joints":
        value = np.asarray(msg.arm_positions, dtype=float)
        if value.shape != (14,):
            raise ValueError("Expected fourteen arm joints")
    elif key == "eef":
        p, q = msg.pose.position, msg.pose.orientation
        value = np.array([p.x, p.y, p.z, q.x, q.y, q.z, q.w])
        if abs(np.linalg.norm(value[3:]) - 1) > .01:
            raise ValueError("Invalid end-effector quaternion")
    elif key.endswith("force"):
        value = wrench_value(msg)
    else:
        value = decode_image_message(msg)
        if key.endswith(("deformation", "shear")) and (value.ndim != 3 or value.shape[2] != 2):
            raise ValueError("Expected HxWx2 numeric field")
    if not np.isfinite(value).all():
        raise ValueError("Nonfinite data")
    return dict(stamp=source_stamp(msg), frame=msg.header.frame_id, value=value)


def age_label(item, stamp):
    if item is None:
        return "WAITING"
    age = (stamp - item["stamp"]) / 1e9
    state = "FUTURE" if age < 0 else "STALE" if age > .25 else "age"
    return f"{state} {age * 1000:.0f}ms"


def camera_preview(value):
    return _crop_square_resize_nearest(value, ObservationConfig().external_rgb_roi, (128, 128))


def tactile_preview_display(value):
    """128px whole-image preview, interpolated back to the raw display footprint.

    Display only: no SDK, rectification, ROI selection, or extra source detail.
    """
    small = _resize_nearest(value, (128, 128))
    return np.asarray(Image.fromarray(small).resize(
        (value.shape[1], value.shape[0]), Image.Resampling.BILINEAR))


def render(latest, stamp, elapsed):
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (18, 22, 28))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    def text(x, y, label, color="white"):
        draw.text((x, y), label, fill=color, font=font)
    text(10, 5, f"RECORDED NATIVE FIELDS | t={elapsed:.2f}s | 10 Hz display | source-header ages shown")
    text(10, 28, "Arrows: step16, 20px/unit, red=clipped at24px. Depth: fixed 0..0.3 SDK units. No force calibration.", "#f1c46b")

    def tile(key, title, col, row, transform=None, square=False):
        x, y = col * 384, 58 + row * 324
        item = latest.get(key)
        text(x+5, y, title)
        text(x+5, y+20, age_label(item, stamp), "#f1c46b" if item is None or stamp-item["stamp"] > 250_000_000 else "#8aefae")
        if item is None:
            return
        value = item["value"]
        value = transform(value) if transform else value
        if value.ndim == 2:
            value = np.repeat(value[..., None], 3, axis=-1)
        im = Image.fromarray(np.asarray(value, dtype=np.uint8))
        im.thumbnail((376, 278), Image.Resampling.NEAREST if square else Image.Resampling.BILINEAR)
        if square:
            im = im.resize((256, 256), Image.Resampling.NEAREST)
        canvas.paste(im, (x+(384-im.width)//2, y+42))

    def camera_original(value):
        _, (left, top, side) = camera_preview(value)
        im = Image.fromarray(value)
        ImageDraw.Draw(im).rectangle((left, top, left+side, top+side), outline="yellow", width=3)
        return np.asarray(im)
    tile("camera", "Camera original + observation ROI", 0, 0, camera_original)
    tile("camera", "Observation ROI 128x128 (2x view)", 1, 0, lambda v: camera_preview(v)[0], True)
    for i, side in enumerate("ab"):
        tile(side+"_raw", side.upper()+" raw -> 128x128 (enlarged)", i+2, 0,
             tactile_preview_display)
        for j, kind in enumerate(("deformation", "shear")):
            tile(side+"_"+kind, side.upper()+" "+kind+" 288x384x2", 2*i+j, 1,
                 lambda v: render_vector_field(v, step=16, scale_px_per_unit=20., deadband=.01, max_arrow_px=24.)[0])
        def depth(v):
            u = np.clip(v/.3, 0, 1)
            return (np.stack((u, np.sqrt(u), 1-u), axis=-1)*255).astype(np.uint8)
        tile(side+"_depth", side.upper()+" depth 288x384 (fixed scale)", i, 2, depth)
        tile(side+"_raw", side.upper()+" tactile raw (original)", i+2, 2)
    for i, side in enumerate("ab"):
        item = latest.get(side+"_force")
        text(10, 1036+i*24, side.upper()+" force [Fx Fy Fz Tx Ty Tz]: " +
             ("WAITING" if item is None else " ".join(f"{v:+.4f}" for v in item["value"])) +
             " | " + age_label(item, stamp))
    item = latest.get("eef")
    text(10, 1084, "Left grasp-center pose [xyz, xyzw]: " + ("WAITING" if item is None else
         " ".join(f"{v:+.4f}" for v in item["value"])))
    text(10, 1108, "EEF: " + age_label(item, stamp) + " | source frame=" + (item["frame"] if item else "?") +
         " | joint feedback: " + age_label(latest.get("joints"), stamp))
    text(10, 1132, "Model/base alignment unverified; no gripper mesh. Independent samples, NOT guaranteed same tactile frame.", "#f1c46b")
    return canvas


def prepare(source, cache_root, *, topics=None, renderer=None, cache_version=None,
            decoder=None, allow_future_headers=False):
    """Stream source to a bounded latest-sample state; atomic cache manifest last."""
    import yaml
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    topics = TOPICS if topics is None else topics
    renderer = render if renderer is None else renderer
    cache_version = VERSION if cache_version is None else cache_version
    decoder = decode if decoder is None else decoder
    if allow_future_headers:
        cache_version = [cache_version, 'receipt-order-future-headers-v1']
    source, cache_root = Path(source).resolve(), Path(cache_root).resolve()
    if source.is_file():
        signature = [(str(source), source.stat().st_size, source.stat().st_mtime_ns)]
    else:
        info = yaml.safe_load((source/"metadata.yaml").read_text())["rosbag2_bagfile_information"]
        paths = [source/"metadata.yaml"] + [(source/p).resolve() for p in info["relative_file_paths"]]
        if any(not p.is_relative_to(source) for p in paths):
            raise ValueError("Bag path escapes source")
        signature = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    key = hashlib.sha256(json.dumps([cache_version, signature]).encode()).hexdigest()[:24]
    dest = cache_root/key
    if (dest/"manifest.json").is_file():
        return dest
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-build-", dir=cache_root) as work:
        work = Path(work)
        if source.is_file():
            with zipfile.ZipFile(source) as archive:
                names = [n for n in archive.namelist() if n.endswith("/metadata.yaml") or n == "metadata.yaml"]
                if len(names) != 1:
                    raise ValueError("ZIP must contain exactly one bag metadata.yaml")
                info = yaml.safe_load(archive.read(names[0]))["rosbag2_bagfile_information"]
                parent = str(Path(names[0]).parent)
                files = []
                import shutil
                for i, relative in enumerate(info["relative_file_paths"]):
                    if Path(relative).is_absolute() or ".." in Path(relative).parts:
                        raise ValueError("Unsafe ZIP bag path")
                    member = relative if parent == "." else parent+"/"+relative
                    path = work/f"source-{i}"
                    with archive.open(member) as src, path.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
                    files.append(path)
        else:
            files = [(source/p).resolve() for p in info["relative_file_paths"]]
        if info["storage_identifier"] != "mcap":
            raise ValueError("Only MCAP supported by this viewer")
        mode = info.get("compression_mode", "").lower()
        if mode not in ("", "none", "file") or (mode == "file" and info.get("compression_format") != "zstd"):
            raise ValueError("Only uncompressed/file-zstd bags supported")
        start = info["starting_time"]["nanoseconds_since_epoch"]
        duration = info["duration"]["nanoseconds"]
        if duration <= 0:
            raise ValueError('Bag duration must be positive')
        build = work/"frames"
        build.mkdir()
        latest, frames, counts = {}, [], {}
        future_headers = {}
        next_frame = start

        def capture(stamp):
            filename = f"{len(frames):06d}.png"
            renderer(latest, stamp, (stamp-start)/1e9).save(build/filename)
            states = {k: dict(stamp=v["stamp"], frame=v["frame"], value=v["value"].tolist())
                      for k, v in latest.items() if k in ("joints", "eef")}
            frames.append(dict(stamp=stamp, image=filename, states=states,
                               source_stamps={k: v["stamp"] for k, v in latest.items()}))
        previous_bag_stamp = start
        for i, path in enumerate(files):
            if mode == "file":
                unpacked = work/f"data-{i}.mcap"
                with unpacked.open("xb") as stream:
                    subprocess.run(["zstd", "-dc", "--", str(path)], stdout=stream, check=True)
                path = unpacked
            reader = rosbag2_py.SequentialReader()
            reader.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="mcap"), rosbag2_py.ConverterOptions("cdr", "cdr"))
            classes = {t.name: get_message(t.type) for t in reader.get_all_topics_and_types() if t.name in topics}
            if not classes:
                raise ValueError("No supported observation topics")
            reader.set_filter(rosbag2_py.StorageFilter(topics=list(classes)))
            while reader.has_next():
                topic, data, stamp = reader.read_next()
                if stamp < previous_bag_stamp:
                    raise ValueError("Bag receive timestamps go backwards")
                previous_bag_stamp = stamp
                while next_frame < stamp:
                    capture(next_frame)
                    next_frame += 100_000_000
                field = topics[topic]
                item = decoder(field, deserialize_message(data, classes[topic]))
                if item["stamp"] > stamp:
                    if not allow_future_headers:
                        raise ValueError("Source header later than bag receipt; clock comparison needs review")
                    warning = future_headers.setdefault(field, {'count': 0, 'max_ahead_ns': 0})
                    warning['count'] += 1
                    warning['max_ahead_ns'] = max(warning['max_ahead_ns'], item['stamp'] - stamp)
                if field in latest and item["stamp"] < latest[field]["stamp"]:
                    raise ValueError("Source timestamp goes backwards")
                latest[field] = item
                counts[field] = counts.get(field, 0)+1
            del reader
        while next_frame <= start+duration:
            capture(next_frame)
            next_frame += 100_000_000
        (build/"manifest.json").write_text(json.dumps(dict(version=cache_version, source=str(source),
            signature=signature, duration_ns=duration, start_ns=start, counts=counts, frames=frames,
            future_headers=future_headers, allow_future_headers=allow_future_headers,
            note='Receipt-order visual review, original source headers preserved; NOT training synchronization',
            recorded_topic_counts={t['topic_metadata']['name']: t['message_count']
                                   for t in info.get('topics_with_message_count', [])})))
        build.rename(dest)
    return dest


def run(cache, rate):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from sensor_msgs.msg import Image as ImageMsg, JointState
    from std_msgs.msg import String
    from visualization_msgs.msg import Marker, MarkerArray
    from geometry_msgs.msg import Point
    from .robot_replay_3d import JOINTS
    from .tactile_live import image_message
    from std_msgs.msg import Header
    manifest = json.loads((cache/"manifest.json").read_text())
    frames = manifest["frames"]
    rclpy.init()
    node = rclpy.create_node("native_recorded_review")
    image_pub = node.create_publisher(ImageMsg, NS+"/dashboard", 1)
    joint_pub = node.create_publisher(JointState, "/omi/replay_3d/joint_states", 2)
    marker_pub = node.create_publisher(MarkerArray, NS+"/eef", 2)
    status_pub = node.create_publisher(String, NS+"/status", 2)
    began, last = time.monotonic(), [-1, -1]
    def tick():
        elapsed = (time.monotonic()-began)*rate
        duration = manifest["duration_ns"]/1e9
        loop, offset = divmod(elapsed, duration)
        index = min(int(offset*10), len(frames)-1)
        if last == [int(loop), index]:
            return
        last[:] = [int(loop), index]
        frame = frames[index]
        now = node.get_clock().now().to_msg()
        header = Header()
        header.stamp.sec, header.stamp.nanosec = divmod(frame["stamp"], 10**9)
        header.frame_id = "recorded_review"
        image_pub.publish(image_message(np.asarray(Image.open(cache/frame["image"]).convert("RGB")), header, "rgb8"))
        joints = frame["states"].get("joints")
        msg = JointState()
        # Never retain the end of the previous loop when the next loop is waiting.
        msg.header.stamp, msg.name, msg.position = now, JOINTS, joints["value"] if joints else [0.]*14
        joint_pub.publish(msg)
        array = MarkerArray()
        clear = Marker()
        clear.action = Marker.DELETEALL
        array.markers.append(clear)
        def marker(ident, kind, frame_id):
            m = Marker()
            m.header.frame_id, m.header.stamp = frame_id, now
            m.ns, m.id, m.type, m.action = "recorded_eef", ident, kind, Marker.ADD
            m.pose.orientation.w = 1.
            m.color.r, m.color.g, m.color.b, m.color.a = 1., .7, .15, 1.
            array.markers.append(m)
            return m
        # Detailed labels stay in the dashboard (more legible than floating 3D text).
        eef = frame["states"].get("eef")
        if eef and eef["frame"] == "base_link":
            from scipy.spatial.transform import Rotation
            values = eef["value"]
            rotation = Rotation.from_quat(values[3:]).as_matrix()
            p = np.asarray(values[:3])
            for i in range(3):
                m = marker(i+1, Marker.ARROW, "omi_replay_robot_base")
                m.scale.x, m.scale.y, m.scale.z = .008, .016, .025
                m.color.r, m.color.g, m.color.b = [float(i == j) for j in range(3)]
                m.points = [Point(x=float(v[0]), y=float(v[1]), z=float(v[2])) for v in (p, p+.09*rotation[:, i])]
        marker_pub.publish(array)
        status_pub.publish(String(data=json.dumps(dict(index=index, loop=int(loop), reference_ns=frame["stamp"],
            source_stamps=frame["source_stamps"], eef=eef,
            joint_state=age_label(joints, frame["stamp"]), neutral_placeholder=joints is None,
            eef_axes_visible=eef is not None and eef["frame"] == "base_link",
            note="Read-only review; not synchronized training samples; base_link assumed model base; alignment unverified"))))
    node.create_timer(.025, tick)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("source", type=Path)
    p.add_argument("cache", type=Path)
    p = sub.add_parser("view")
    p.add_argument("cache", type=Path)
    p.add_argument("--rate", type=float, default=1.)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(prepare(args.source, args.cache))
    else:
        if not np.isfinite(args.rate) or args.rate <= 0:
            parser.error("rate must be positive and finite")
        run(args.cache, args.rate)


if __name__ == "__main__":
    main()
