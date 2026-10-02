"""Reconstruct tactile fields or display their numeric ROS topics in a separate process."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from .ros_topics import decode_image_message
from .tactile_offline import TOPICS, _nearest_resize
from .tactile_vectors import render_vector_field

PREFIX = "/omi/tactile"
VERSION = "daimon-cpu-fixed-baseline-v1"
RENDER = dict(step=16, scale_px_per_unit=2.0, deadband=0.2, max_arrow_px=24.0)


def stamp_ns(header):
    return int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)


def image_message(array, header, encoding):
    from sensor_msgs.msg import Image

    value = np.ascontiguousarray(array, dtype="<f4" if encoding == "32FC2" else np.uint8)
    message = Image()
    message.header = header
    message.height, message.width = value.shape[:2]
    message.encoding = encoding
    message.is_bigendian = False
    message.step = value.strides[0]
    message.data = value.tobytes()
    return message


def validate_field(value):
    value = np.asarray(value)
    if value.ndim != 3 or value.shape[2] != 2 or min(value.shape[:2]) < 1:
        raise ValueError("expected H x W x 2 field")
    if value.dtype.kind != "f" or not np.isfinite(value).all():
        raise ValueError("expected finite floating point field")
    return np.asarray(value, dtype=np.float32)


class FrameJoiner:
    """Bounded exact-stamp join; never display deformation and shear from different frames."""

    def __init__(self):
        self.pending = OrderedDict()
        self.last_stamp = None

    def add(self, kind, stamp, value):
        # A backwards raw timestamp marks a bag loop or seek.
        if kind == "raw":
            if self.last_stamp is not None and stamp < self.last_stamp:
                current = self.pending.get(stamp)
                self.pending.clear()
                if current is not None:
                    self.pending[stamp] = current
            self.last_stamp = stamp
        entry = self.pending.setdefault(stamp, {})
        entry[kind] = value
        while len(self.pending) > 8:
            self.pending.popitem(last=False)
        if {"raw", "deformation", "shear", "metadata"} <= entry.keys():
            del self.pending[stamp]
            return entry
        return None


class FieldProcessor:
    def __init__(self, baseline_dir, sdk_root):
        if not (sdk_root / "dmrobotics").is_dir():
            raise FileNotFoundError(f"SDK not found: {sdk_root}")
        sys.path.insert(0, str(sdk_root.resolve()))
        from dmrobotics.src.dmSDK import Decomposer, FlowTracker

        self.decomposer_class = Decomposer
        self.trackers = {}
        self.decomposers = {}
        metadata_bytes = (baseline_dir / "metadata.json").read_bytes()
        self.identity = json.loads(metadata_bytes).get("sensor_identity", {})
        digest = hashlib.sha256(metadata_bytes)
        bases = {}
        for side in ("a", "b"):
            path = baseline_dir / f"tactile_{side}_base.npy"
            digest.update(path.read_bytes())
            base = np.load(path, allow_pickle=False)
            if base.ndim != 2 or base.dtype != np.uint8:
                raise ValueError("baseline must be mono8 H x W")
            bases[side] = base
        self.baseline_id = digest.hexdigest()
        sdk_digest = hashlib.sha256()
        for path in sorted((sdk_root / "dmrobotics").rglob("*.py")):
            sdk_digest.update(str(path.relative_to(sdk_root)).encode())
            sdk_digest.update(path.read_bytes())
        self.sdk_hash = sdk_digest.hexdigest()
        self.shapes = {side: base.shape for side, base in bases.items()}
        try:
            for side, base in bases.items():
                tracker = FlowTracker(backend="cpu", model_path="standard")
                self.trackers[side] = tracker
                tracker.setBaseFrame(base)
        except Exception:
            self.close()
            raise

    def process(self, side, raw):
        if raw.shape != self.shapes[side] or raw.dtype != np.uint8:
            raise ValueError("raw shape/dtype does not match baseline")
        deformation = validate_field(self.trackers[side].t(raw))
        shape = deformation.shape[:2]
        if side not in self.decomposers:
            self.decomposers[side] = self.decomposer_class(shape, (1, 1), "cpu")
        shear = validate_field(self.decomposers[side].decompose(deformation))
        if shear.shape != deformation.shape:
            raise ValueError("shear/deformation shapes differ")
        return deformation, shear

    def close(self):
        for tracker in self.trackers.values():
            tracker.close()


def dashboard(samples, now, stale_s=0.5):
    from PIL import Image, ImageDraw

    sheet = Image.new("RGB", (1152, 740), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), "TACTILE | image +x right, +y down | units uncalibrated (NOT N)", fill="white")
    draw.text((10, 26), "step=16  scale=2 px/unit  deadband=0.2  max=24 px (red=clipped)", fill="white")
    draw.text((10, 44), "Exact source-stamp join per finger; A/B asynchronous | age = wall time since received", fill="white")
    for row, side in enumerate(("a", "b")):
        y = 70 + row * 334
        sample = samples.get(side)
        if sample is None:
            draw.text((10, y), f"{side.upper()}: WAITING for matching raw / deformation / shear / metadata", fill="orange")
            continue
        age = max(0.0, now - sample["received"])
        meta = sample["metadata"]
        stale = age > stale_s
        identity = meta.get("identity", {})
        label = f"{side.upper()} {identity.get('physical_side', '?')} {identity.get('serial', '?')}"
        draw.text((10, y), f"{label} | {'STALE' if stale else 'VALID'} age={age:.2f}s source_ns={meta['source_timestamp_ns']}", fill="orange" if stale else "white")
        draw.text((10, y + 16), f"base={meta['baseline_id'][:12]} compute={meta['processing_ms']:.1f}ms  {VERSION}", fill="white")
        raw = _nearest_resize(sample["raw"], (288, 384))
        panels = [np.repeat(raw[..., None], 3, axis=2)]
        labels = ["raw"]
        for kind in ("deformation", "shear"):
            field = sample[kind]
            rgb, stats = render_vector_field(field, background=_nearest_resize(sample["raw"], field.shape[:2]), **RENDER)
            panels.append(_nearest_resize(rgb, (288, 384)))
            labels.append(f"{kind}  clipped={stats.clipped_vectors}")
        for column, (label, panel) in enumerate(zip(labels, panels)):
            draw.text((column * 384 + 10, y + 32), label, fill="white")
            sheet.paste(Image.fromarray(panel), (column * 384, y + 46))
    return np.asarray(sheet).copy()


def run(args):
    os.environ.setdefault("RMW_FASTRTPS_PUBLICATION_MODE", "ASYNCHRONOUS")
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
    from std_msgs.msg import String

    rclpy.init(args=[])
    node = rclpy.create_node(f"omi_tactile_{args.mode}")
    qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE)
    raw_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    processor = None
    try:
        if args.mode == "fields":
            processor = FieldProcessor(args.baseline_dir, args.sdk_root)
            publishers = {
                (side, kind): node.create_publisher(String if kind == "metadata" else Image, f"{PREFIX}/{side}/{kind}", qos)
                for side in ("a", "b") for kind in ("raw", "deformation", "shear", "metadata")
            }
            pending = {}

            def receive(side, message):
                pending[side] = (message, time.time_ns())

            for side in ("a", "b"):
                node.create_subscription(Image, TOPICS[side]["raw"], lambda msg, s=side: receive(s, msg), raw_qos)

            def process():
                for side in ("a", "b"):
                    item = pending.pop(side, None)
                    if item is None:
                        continue
                    message, received_ns = item
                    try:
                        source_ns = stamp_ns(message.header)
                        if source_ns <= 0:
                            raise ValueError("raw requires a nonzero source timestamp")
                        raw = decode_image_message(message)
                        start = time.monotonic()
                        deformation, shear = processor.process(side, raw)
                        meta = dict(schema_version=1, side=side, source_timestamp_ns=source_ns,
                                    received_timestamp_ns=received_ns, baseline_id=processor.baseline_id,
                                    identity=processor.identity.get(f"tactile_{side}", {}),
                                    processing_version=VERSION, sdk_python_sha256=processor.sdk_hash,
                                    shape=list(deformation.shape), dtype="float32", valid=True,
                                    units="uncalibrated", frame="image_x_right_y_down",
                                    processing_ms=(time.monotonic() - start) * 1000)
                        for kind, value, encoding in (("raw", raw, "mono8"), ("deformation", deformation, "32FC2"), ("shear", shear, "32FC2")):
                            publishers[side, kind].publish(image_message(value, message.header, encoding))
                        publishers[side, "metadata"].publish(String(data=json.dumps(meta)))
                    except Exception as exc:
                        if not rclpy.ok():
                            return
                        node.get_logger().error(f"{side}: rejected frame: {exc}")
            node.create_timer(1 / args.rate, process)
        else:
            joiners = {side: FrameJoiner() for side in ("a", "b")}
            samples = {}
            publisher = node.create_publisher(Image, f"{PREFIX}/dashboard", qos)
            last_header = [None]

            def receive(side, kind, message):
                try:
                    if kind == "metadata":
                        value = json.loads(message.data)
                        source = value["source_timestamp_ns"]
                        if not value["valid"]:
                            return
                    else:
                        source = stamp_ns(message.header)
                        value = decode_image_message(message)
                        if kind != "raw":
                            value = validate_field(value)
                        last_header[0] = message.header
                    sample = joiners[side].add(kind, source, value)
                    if sample is not None:
                        sample["received"] = time.monotonic()
                        samples[side] = sample
                except Exception as exc:
                    node.get_logger().error(f"{side}/{kind}: rejected: {exc}")

            for side in ("a", "b"):
                for kind in ("raw", "deformation", "shear", "metadata"):
                    node.create_subscription(String if kind == "metadata" else Image, f"{PREFIX}/{side}/{kind}", lambda msg, s=side, k=kind: receive(s, k, msg), qos)

            def render():
                if last_header[0] is not None:
                    publisher.publish(image_message(dashboard(samples, time.monotonic()), last_header[0], "rgb8"))
            node.create_timer(1 / args.rate, render)
        node.get_logger().info(f"READY {args.mode}: {PREFIX}")
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception:
        # SIGTERM may invalidate the ROS context during a publish call.
        if rclpy.ok():
            raise
    finally:
        if processor is not None:
            processor.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fields", "dashboard"))
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--sdk-root", type=Path)
    parser.add_argument("--rate", type=float, default=10)
    args = parser.parse_args()
    if not np.isfinite(args.rate) or args.rate <= 0:
        parser.error("rate must be finite and positive")
    if args.mode == "fields" and (args.baseline_dir is None or args.sdk_root is None):
        parser.error("fields requires --baseline-dir and --sdk-root")
    run(args)


if __name__ == "__main__":
    main()
