"""SDK-native numeric dashboard. No SDK import, reconstruction or robot control.

Pure DashboardState/render functions support tests without ROS. Runtime subscribes
to schema2 samples and publishes only a human-view RGB image and diagnostic JSON.
"""

from collections import OrderedDict, deque
import copy
import json
import time

import numpy as np

from .dashboard_vectors import render_vector_field

WIDTH, HEIGHT = 1536, 1000
CORE = {"raw", "infer", "deformation", "shear", "metadata"}
RENDER = dict(step=16, scale_px_per_unit=2.0, deadband=0.2, max_arrow_px=24.0)


def stamp_ns(header):
    return int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)


def decode_image(msg):
    enc = msg.encoding.lower()
    specs = {"mono8": ("u1", 1), "rgb8": ("u1", 3), "bgr8": ("u1", 3),
             "rgba8": ("u1", 4), "bgra8": ("u1", 4), "32fc1": ("f4", 1), "32fc2": ("f4", 2)}
    if enc not in specs:
        raise ValueError("unsupported encoding: " + enc)
    code, channels = specs[enc]
    dtype = np.dtype((">" if msg.is_bigendian else "<") + code)
    h, w, step = int(msg.height), int(msg.width), int(msg.step)
    if min(h, w) <= 0 or step < w * channels * dtype.itemsize or step % dtype.itemsize:
        raise ValueError("invalid image dimensions/stride")
    if len(msg.data) != h * step:
        raise ValueError("image payload does not match stride")
    value = np.frombuffer(bytes(msg.data), dtype=dtype).reshape(h, step // dtype.itemsize)[:, :w * channels]
    if channels > 1:
        value = value.reshape(h, w, channels)
    if enc in ("bgr8", "bgra8"):
        value = value[..., [2, 1, 0]]
    elif enc == "rgba8":
        value = value[..., :3]
    value = np.asarray(value, dtype=dtype.newbyteorder("=")).copy()
    if not np.isfinite(value).all():
        raise ValueError("image contains NaN/Inf")
    return value


def _rgb(value):
    return np.repeat(value[..., None], 3, axis=-1) if value.ndim == 2 else value


class DashboardState:
    def __init__(self, config, stale_s=0.5):
        self.config, self.stale_s = config, stale_s
        self.pending = {s: OrderedDict() for s in ("a", "b")}
        self.samples, self.errors, self.status = {}, {}, {}
        self.last_meta, self.epochs = {}, {s: 0 for s in ("a", "b")}
        self.rates = {s: deque(maxlen=120) for s in ("a", "b", "camera")}
        self.counts = {s: 0 for s in ("a", "b")}
        self.rejected = {s: 0 for s in ("a", "b", "camera")}
        self.camera, self.camera_info = None, OrderedDict()

    def reject(self, side, error):
        self.errors[side] = str(error)[:180]
        self.rejected[side] += 1

    def add(self, side, kind, stamp, value, now):
        try:
            if kind == "status":
                if not isinstance(value, dict) or not isinstance(value.get("state"), str):
                    raise ValueError("invalid status JSON")
                self.status[side] = (value, now)
                return
            if stamp <= 0:
                raise ValueError("missing source timestamp")
            if kind == "metadata":
                if not isinstance(value, dict) or value.get("schema_version") != 2 or value.get("side") != side:
                    raise ValueError("expected schema2 metadata with matching side; legacy fields need the old viewer")
                if value.get("valid") is not True or value.get("field_source") not in ("sdk_direct", "synthetic"):
                    raise ValueError("invalid sample or unsupported field_source")
                if value.get("source_timestamp_ns") != stamp or type(value.get("frame_id")) is not int or value["frame_id"] < 0:
                    raise ValueError("invalid metadata stamp/fid")
                if not isinstance(value.get("identity"), dict) or not isinstance(value.get("fields"), dict):
                    raise ValueError("metadata identity/fields missing")
                if not isinstance(value.get("baseline_id"), str) or not isinstance(value.get("timestamp_kind"), str):
                    raise ValueError("metadata baseline/timestamp kind missing")
                previous = self.last_meta.get(side)
                if previous and stamp < previous[0] and value["frame_id"] <= previous[1]:
                    # Per-topic reliable order; backward stamp+fid marks loop/restart.
                    current = self.pending[side].get(stamp)
                    self.pending[side].clear()
                    if current is not None:
                        self.pending[side][stamp] = current
                    self.samples.pop(side, None)
                    self.rates[side].clear()
                    self.status.pop(side, None)
                    self.epochs[side] += 1
                self.last_meta[side] = (stamp, value["frame_id"])
            elif kind in ("raw", "infer"):
                if value.dtype != np.uint8 or value.size == 0 or not (value.ndim == 2 or (value.ndim == 3 and value.shape[2] == 3)):
                    raise ValueError(kind + " must be mono/RGB uint8")
            elif kind in ("deformation", "shear", "depth"):
                if value.dtype != np.float32 or not np.isfinite(value).all() or value.size == 0:
                    raise ValueError(kind + " must be finite float32")
                if (kind == "depth" and value.ndim != 2) or (kind != "depth" and (value.ndim != 3 or value.shape[2] != 2)):
                    raise ValueError(kind + " shape invalid")
            elif kind == "wrench":
                if value.shape != (6,) or not np.isfinite(value).all():
                    raise ValueError("invalid wrench")
            else:
                raise ValueError("unknown sample field")
            entry = self.pending[side].setdefault(stamp, {"data": {}, "first_received": now})
            if entry.get("complete") and kind in CORE:
                # Once shown, the matched core is immutable; duplicate packets
                # must not replace a validated array without re-validating metadata.
                return
            entry["data"][kind] = value.copy() if isinstance(value, np.ndarray) else copy.deepcopy(value)
            while len(self.pending[side]) > 8:
                self.pending[side].popitem(last=False)
            data = entry["data"]
            if not CORE <= data.keys() or entry.get("complete"):
                return
            meta = data["metadata"]
            for key in CORE - {"metadata"}:
                declared = meta["fields"].get(key, {})
                original_shape = declared.get("shape")
                # Color decoding converts BGRA->RGB; the spatial shape must agree.
                shape = list(data[key].shape)
                if key in ("raw", "infer") and original_shape and len(original_shape) == 3 and original_shape[-1] == 4:
                    original_shape = original_shape[:2] + [3]
                if original_shape != shape or declared.get("dtype") != str(data[key].dtype):
                    raise ValueError("metadata/array mismatch: " + key)
            if data["deformation"].shape != data["shear"].shape:
                raise ValueError("deformation/shear geometry mismatch")
            current = self.samples.get(side)
            if current is not None and stamp <= current["stamp"]:
                return
            entry.update(complete=True, received=now, stamp=stamp)
            self.samples[side] = entry
            self.errors.pop(side, None)
            self.rates[side].append(now)
            self.counts[side] += 1
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.reject(side, exc)

    def add_camera(self, stamp, value, now):
        if stamp <= 0 or value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
            self.reject("camera", "camera must be stamped RGB uint8")
            return
        if self.camera and stamp < self.camera["stamp"]:
            # Keep matching info that may have arrived before this image.
            current = self.camera_info.get(stamp)
            self.camera_info.clear()
            if current is not None:
                self.camera_info[stamp] = current
            self.rates["camera"].clear()
        self.camera = dict(stamp=stamp, value=value.copy(), received=now)
        self.errors.pop("camera", None)
        self.rates["camera"].append(now)

    def rate(self, side, now):
        times = [t for t in self.rates[side] if now - t <= 2.0]
        return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0

    def summary(self, now):
        result = {"schema_version": 1, "camera": {}, "sides": {}}
        for side in ("a", "b", "camera"):
            enabled = self.config["realsense" if side == "camera" else "tactile"]["enabled"]
            sample = self.camera if side == "camera" else self.samples.get(side)
            age = max(0.0, now - sample["received"]) if sample else None
            state = "DISABLED" if not enabled else "INVALID" if side in self.errors else "WAITING" if sample is None else "STALE" if age > self.stale_s else "VALID"
            item = {"state": state, "receive_age_s": age, "receive_hz": self.rate(side, now),
                    "error": self.errors.get(side, ""), "rejected": self.rejected[side]}
            if side == "camera":
                item["source_timestamp_ns"] = sample["stamp"] if sample else None
                info = self.camera_info.get(sample["stamp"]) if sample else None
                item["intrinsics_matched"] = bool(info and (info["height"], info["width"]) == sample["value"].shape[:2])
                result["camera"] = item
            else:
                item.update(complete_frames=self.counts[side], pending=len(self.pending[side]), epochs=self.epochs[side])
                if sample:
                    meta = sample["data"]["metadata"]
                    item.update(source_timestamp_ns=sample["stamp"], fid=meta["frame_id"], field_source=meta["field_source"])
                    if state == "VALID" and meta["field_source"] == "synthetic":
                        item["state"] = "SYNTHETIC"
                if side in self.status:
                    value, received = self.status[side]
                    item.update(device_status=value, status_receive_age_s=max(0.0, now - received))
                    if item["state"] in ("VALID", "SYNTHETIC") and now - received < 2 and value["state"] in ("retrying", "incomplete", "stale"):
                        item["state"] = "DEVICE_WARNING"
                result["sides"][side] = item
        return result


def render(state, now):
    from PIL import Image, ImageDraw, ImageOps

    sheet = Image.new("RGB", (WIDTH, HEIGHT), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    summary = state.summary(now)

    def text(x, y, value, color="white", max_chars=120):
        # Vendor errors may contain Unicode unsupported by the default font.
        draw.text((x, y), str(value)[:max_chars].encode("ascii", "replace").decode(), fill=color)

    def tile(array, box):
        image = Image.fromarray(_rgb(array))
        image = ImageOps.contain(image, (box[2], box[3]))
        sheet.paste(image, (box[0] + (box[2] - image.width) // 2, box[1] + (box[3] - image.height) // 2))

    text(12, 10, "OMI SDK-NATIVE VIEW | numeric topic subscriber only | no image reconstruction / no robot commands")
    text(12, 30, "Vectors: +x right, +y down | fixed scale=2 px/unit, step=16, deadband=0.2, max=24 px | RED=display clipping, NOT force", "#b7c5d3", 180)
    text(12, 48, "Age/FPS = monotonic time since reception; bag pause becomes STALE. A/B/camera are NOT hardware synchronized.", "#b7c5d3", 180)
    camera = summary["camera"]
    text(12, 72, "REALSENSE COLOR | " + camera["state"] + " | %.1f Hz" % camera["receive_hz"], "orange" if camera["state"] != "VALID" else "#69df8e")
    if state.camera:
        array = state.camera["value"]
        h, w = array.shape[:2]
        size = max(1, int(round(min(h, w) * 0.40)))
        left = max(0, min(w - size, int(round(w * .507)) - size // 2))
        top = max(0, min(h - size, int(round(h * .426)) - size // 2))
        full = Image.fromarray(array)
        ImageDraw.Draw(full).rectangle((left, top, left + size - 1, top + size - 1), outline=(60, 255, 90), width=2)
        tile(np.asarray(full), (12, 94, 384, 216))
        resampling = getattr(Image, "Resampling", Image)  # Ubuntu 22.04 ships Pillow 9.0.
        crop = Image.fromarray(array[top:top + size, left:left + size]).resize((128, 128), resampling.NEAREST)
        sheet.paste(crop, (420, 112))
        text(410, 94, "128px ROI PREVIEW", "#b7c5d3")
        text(410, 254, "Display only; not RL input", "#b7c5d3")
        text(580, 98, "Original %dx%d | ROI=(%d,%d,%d) | age=%.2fs" % (w, h, left, top, size, camera["receive_age_s"]))
        text(580, 122, "source_ns=" + str(state.camera["stamp"]))
        info = state.camera_info.get(state.camera["stamp"])
        if info is not None and info["width"] == w and info["height"] == h:
            k = info["k"]
            calibrated = k[0] > 0 and k[4] > 0
            text(580, 148, ("MATCHED INTRINSICS" if calibrated else "UNCALIBRATED K") + " | " + info["model"], "#69df8e" if calibrated else "orange")
            text(580, 172, "fx=%.2f fy=%.2f cx=%.2f cy=%.2f" % (k[0], k[4], k[2], k[5]))
            text(580, 196, "D=" + str(info["d"]))
        else:
            text(580, 148, "INTRINSICS WAITING / timestamp or dimensions mismatch", "orange")
    if camera["error"]:
        text(580, 220, camera["error"], "orange")
    text(580, 248, "No wrist stream in this SDK-native viewer. Optional depth/wrench never block the core panels.", "#b7c5d3")

    for row, side in enumerate(("a", "b")):
        y = 334 + row * 326
        status = summary["sides"][side]
        sample = state.samples.get(side)
        text(12, y, side.upper() + " | " + status["state"] + " | %.1f Hz | rejected=%d" % (status["receive_hz"], status["rejected"]), "#69df8e" if status["state"] == "VALID" else "orange")
        if status["error"]:
            text(480, y, "ERROR: " + status["error"], "orange")
        if sample is None:
            text(12, y + 30, "Waiting for exact-stamp raw + infer + deformation + shear + schema2 metadata. No SDK is loaded.", "#b7c5d3")
            continue
        data, meta = sample["data"], sample["data"]["metadata"]
        identity = meta["identity"]
        text(12, y + 18, "source=%s | fid=%s | %s %s | age=%.2fs | stamp=%s" % (meta["field_source"], meta["frame_id"], identity.get("physical_side", "?"), identity.get("serial") or "serial unknown", status["receive_age_s"], sample["stamp"]), "#b7c5d3", 170)
        text(12, y + 36, "base=%s | %s | %s | %s" % (meta["baseline_id"][:24], meta["timestamp_kind"], meta.get("processing_version", "?"), meta.get("units", "units unknown")), "#b7c5d3", 190)
        for column, kind in enumerate(("raw", "infer", "deformation", "shear")):
            array = data[kind]
            label = kind + " " + str(tuple(array.shape))
            value_range = "component min/max: %.3g / %.3g" % (float(array.min()), float(array.max()))
            if kind in ("deformation", "shear"):
                # No infer overlay: raw/infer and field registration has not been calibrated.
                array, stats = render_vector_field(array, **RENDER)
                label += " clipped=%d" % stats.clipped_vectors
            text(column * 384 + 12, y + 58, label)
            text(column * 384 + 12, y + 72, value_range, "#b7c5d3")
            tile(array, (column * 384 + 8, y + 90, 368, 208))
        optional = []
        for kind, flag in (("depth", "enable_depth"), ("wrench", "enable_wrench")):
            if not state.config["tactile"][flag]:
                optional.append(kind + " OFF")
            elif kind not in data:
                optional.append(kind + " missing (same stamp)")
            else:
                value = data[kind]
                optional.append(kind + (" min/max=%.3g/%.3g" % (value.min(), value.max()) if kind == "depth" else "=" + np.array2string(value, precision=2)))
        device = status.get("device_status", {})
        optional.append("device=" + device.get("state", "unknown") + " " + str(device.get("error", "")))
        text(12, y + 304, " | ".join(optional), "#b7c5d3", 200)
    return np.asarray(sheet).copy(), summary


def run(config, rate=10.0, stale_s=0.5):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image, CameraInfo
    from geometry_msgs.msg import WrenchStamped
    from std_msgs.msg import String

    state = DashboardState(config, stale_s)
    rclpy.init(args=[])
    node = rclpy.create_node("omi_sdk_native_dashboard")
    sensor_qos = QoSProfile(depth=8, reliability=ReliabilityPolicy.BEST_EFFORT)
    output_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
    image_pub = node.create_publisher(Image, "/omi/sdk/dashboard", output_qos)
    status_pub = node.create_publisher(String, "/omi/sdk/dashboard_status", output_qos)

    def receive(side, kind, msg):
        try:
            if kind in ("metadata", "status"):
                value = json.loads(msg.data)
                stamp = value.get("source_timestamp_ns", 0) if isinstance(value, dict) else 0
            elif kind == "wrench":
                w = msg.wrench
                value = np.asarray([w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z])
                stamp = stamp_ns(msg.header)
            else:
                value, stamp = decode_image(msg), stamp_ns(msg.header)
            state.add(side, kind, stamp, value, time.monotonic())
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            state.reject(side, exc)

    if config["tactile"]["enabled"]:
        for side in ("a", "b"):
            kinds = list(CORE) + ["status"]
            if config["tactile"]["enable_depth"]:
                kinds.append("depth")
            if config["tactile"]["enable_wrench"]:
                kinds.append("wrench")
            for kind in kinds:
                cls = String if kind in ("metadata", "status") else WrenchStamped if kind == "wrench" else Image
                node.create_subscription(cls, "/omi/tactile/%s/%s" % (side, kind), lambda msg, s=side, k=kind: receive(s, k, msg), sensor_qos)

    def camera(msg):
        try:
            state.add_camera(stamp_ns(msg.header), decode_image(msg), time.monotonic())
        except (ValueError, TypeError) as exc:
            state.reject("camera", exc)

    def info(msg):
        try:
            k, d = np.asarray(msg.k), np.asarray(msg.d)
            if k.size != 9 or not np.isfinite(k).all() or not np.isfinite(d).all() or stamp_ns(msg.header) <= 0:
                raise ValueError("invalid CameraInfo")
            state.camera_info[stamp_ns(msg.header)] = dict(k=k.tolist(), d=d.tolist(), width=msg.width, height=msg.height, model=msg.distortion_model)
            while len(state.camera_info) > 12:
                state.camera_info.popitem(last=False)
        except (ValueError, TypeError) as exc:
            state.reject("camera", exc)

    if config["realsense"]["enabled"]:
        node.create_subscription(Image, "/camera/camera/color/image_raw", camera, sensor_qos)
        node.create_subscription(CameraInfo, "/camera/camera/color/camera_info", info, sensor_qos)

    def publish():
        pixels, status = render(state, time.monotonic())
        msg = Image()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.height, msg.width, msg.encoding, msg.step = HEIGHT, WIDTH, "rgb8", WIDTH * 3
        msg.data = pixels.tobytes()
        image_pub.publish(msg)
        status_pub.publish(String(data=json.dumps(status)))

    node.create_timer(1.0 / rate, publish)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
