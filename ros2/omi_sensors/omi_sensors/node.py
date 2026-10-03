"""Live tactile and deterministic synthetic publishers (standard ROS messages)."""

import json
import time

import numpy as np

from .tactile import IncompleteFrame, connect, snapshot, sdk_check, sdk_digest
from .tactile_grid import prepare_fields, topic_root


def image_message(array, header):
    from sensor_msgs.msg import Image
    array = np.asarray(array)
    if array.dtype == np.uint8:
        encoding = "mono8" if array.ndim == 2 else {3: "bgr8", 4: "bgra8"}[array.shape[2]]
    else:
        encoding = "32FC1" if array.ndim == 2 else "32FC2"
        array = array.astype("<f4")
    array = np.ascontiguousarray(array)
    msg = Image()
    msg.header = header
    msg.height, msg.width = array.shape[:2]
    msg.encoding, msg.is_bigendian = encoding, False
    msg.step, msg.data = array.strides[0], array.tobytes()
    return msg


def run(config, side=None, fake=False, duration=None, tactile_mode='full', publish_raw=False):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from sensor_msgs.msg import Image, CameraInfo
    from std_msgs.msg import Header, String
    from geometry_msgs.msg import WrenchStamped
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    root = topic_root(tactile_mode)
    tac = config["tactile"]
    digest = "synthetic"
    if not fake:
        digest = sdk_digest(sdk_check(tac))
    rclpy.init(args=[])
    node = rclpy.create_node("omi_synthetic_sensors" if fake else "omi_tactile_" + side)
    qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE)
    sides = (["a", "b"] if fake else [side]) if tac["enabled"] else []
    pubs = {}
    for s in sides:
        for kind in ("raw", "infer", "deformation", "shear", "depth", "metadata", "status", "wrench"):
            if tactile_mode != 'full' and ((kind == 'raw' and not publish_raw) or kind == 'infer' or
                    (kind == 'depth' and not tac['enable_depth']) or
                    (kind == 'wrench' and not tac['enable_wrench'])):
                continue
            cls = String if kind in ("metadata", "status") else WrenchStamped if kind == "wrench" else Image
            kind_root = '/omi/tactile' if kind == 'raw' else root
            pubs[s, kind] = node.create_publisher(cls, kind_root + "/%s/%s" % (s, kind), qos)
    camera = None
    if fake and config["realsense"]["enabled"]:
        camera = (node.create_publisher(Image, "/camera/camera/color/image_raw", qos),
                  node.create_publisher(CameraInfo, "/camera/camera/color/camera_info", qos))
    started = time.monotonic()
    sensor, fid, dropped = None, -1, 0
    retry_at, last_good, last_status = 0.0, started, 0.0
    state, error = "starting", ""

    def publish(s, frame, stamp, arrays, wrench_state, elapsed):
        reduction_start = time.monotonic()
        raw = arrays.get('raw') if publish_raw else None
        arrays, reduction_meta = prepare_fields(arrays, tactile_mode)
        if reduction_meta:
            if raw is not None:
                arrays['raw'] = raw
                reduction_meta['omitted_fields'].remove('raw')
                reduction_meta['raw_topic'] = '/omi/tactile/' + s + '/raw'
            elapsed += (time.monotonic() - reduction_start) * 1000
            reduction_meta['field_source'] = 'synthetic_downsampled' if fake else 'sdk_downsampled'
            if fake:
                reduction_meta['processing_version'] = 'synthetic-block-mean-24x16-v1'
        header = Header()
        header.stamp.sec, header.stamp.nanosec = divmod(stamp, 1_000_000_000)
        header.frame_id = "tactile_" + s
        for kind, array in arrays.items():
            if kind == "wrench":
                msg = WrenchStamped()
                msg.header = header
                msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z = map(float, array[:3])
                msg.wrench.torque.x, msg.wrench.torque.y, msg.wrench.torque.z = map(float, array[3:])
            else:
                msg = image_message(array, header)
            pubs[s, kind].publish(msg)
        meta = {
            "schema_version": 2, "side": s, "frame_id": frame, "source_timestamp_ns": stamp,
            "timestamp_kind": "synthetic_host_time" if fake else "host_receive_not_exposure",
            "identity": {"serial": tac["sensors"][s]["serial"], "physical_side": tac["sensors"][s]["physical_side"],
                         "identity_source": "configuration_not_device_verified"},
            "baseline_id": "unknown_vendor_managed", "baseline_reproducible": False,
            "processing_version": "synthetic-v1" if fake else "vendor-flux-v1",
            "field_source": "synthetic" if fake else "sdk_direct",
            "sdk_sha256": digest, "processing_ms": elapsed, "valid": True,
            "units": "SDK units; NOT calibrated force", "wrench_state": wrench_state,
            "fields": {key: {"shape": list(a.shape), "dtype": str(a.dtype)} for key, a in arrays.items()},
            "dropped_incomplete_frames": dropped,
        }
        meta.update(reduction_meta)
        if 'wrench' in arrays:
            matched = wrench_state == 'frame_id_matched_units_unverified'
            meta['wrench_provenance'] = {
                'source_frame_id': frame if matched else None,
                'same_frame_as_fields_verified': matched,
                'timestamp_kind': 'host_read_not_exposure',
                'source_timestamp_available': False,
                'freshness_verified': False,
                'units_and_axes_calibrated': False,
                'component_order': ['Fx', 'Fy', 'Fz', 'Tx', 'Ty', 'Tz'],
            }
        pubs[s, "metadata"].publish(String(data=json.dumps(meta, sort_keys=True)))

    try:
        while rclpy.ok() and (duration is None or time.monotonic() - started < duration):
            tick = time.monotonic()
            if fake:
                fid += 1
                stamp = time.time_ns()
                height, width = (48, 64) if tactile_mode == 'full' else (288, 384)
                yy, xx = np.mgrid[:height, :width]
                mono = ((xx + yy + fid) % 256).astype(np.uint8)
                field = np.stack((np.sin((xx + fid) / 10), np.cos(yy / 10)), axis=-1).astype(np.float32)
                arrays = {"raw": mono, "infer": mono.copy(), "deformation": field, "shear": field * 0.5}
                if tac["enable_depth"]:
                    arrays["depth"] = np.linalg.norm(field, axis=-1)
                for s in sides:
                    publish(s, fid, stamp, arrays, "synthetic_wrench_not_generated", 0.0)
                if camera:
                    header = Header()
                    header.stamp.sec, header.stamp.nanosec = divmod(stamp, 1_000_000_000)
                    header.frame_id = "camera_color_optical_frame"
                    width, height, _ = map(int, config["realsense"]["color_profile"].split("x"))
                    # Obvious synthetic color chart, useful for inspecting ROI and
                    # color order without confusing a dark test frame with dropout.
                    rgb = np.zeros((height, width, 3), dtype=np.uint8)
                    rgb[:, :, 0] = np.arange(width, dtype=np.uint32)[None, :] * 255 // max(1, width - 1)
                    rgb[:, :, 1] = np.arange(height, dtype=np.uint32)[:, None] * 255 // max(1, height - 1)
                    rgb[:, :, 2] = (fid * 4) % 256
                    camera[0].publish(image_message(rgb, header))
                    info = CameraInfo()
                    info.header, info.width, info.height = header, width, height
                    info.distortion_model, info.d = "plumb_bob", [0.0] * 5
                    info.k = [float(width), 0., width / 2, 0., float(height), height / 2, 0., 0., 1.]
                    info.r = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
                    info.p = [float(width), 0., width / 2, 0., 0., float(height), height / 2, 0., 0., 0., 1., 0.]
                    camera[1].publish(info)
                state, error, last_good = "synthetic", "", time.monotonic()
            elif tick >= retry_at:
                try:
                    if sensor is None:
                        state = "connecting"
                        sensor = connect(tac, side)
                        fid, last_good = -1, tick
                    sensor.getEvents()
                    if sensor.getDevStatus() == 0 and sensor.wait_for_new(fid, timeout_ms=100):
                        new_fid, stamp, arrays, wrench_state = snapshot(sensor, tac["enable_depth"], tac["enable_wrench"])
                        if new_fid != fid:
                            publish(side, new_fid, stamp, arrays, wrench_state, (time.monotonic() - tick) * 1000)
                            fid, last_good = new_fid, time.monotonic()
                            state, error = "streaming", ""
                    if time.monotonic() - last_good > 5:
                        raise RuntimeError("no complete matched SDK frame for 5 seconds")
                except IncompleteFrame as exc:
                    dropped += 1
                    state, error = "incomplete", str(exc)
                    # Continue polling; never attach stale fields to a new image.
                    if time.monotonic() - last_good > 5:
                        if sensor is not None:
                            try:
                                sensor.disconnect()
                            except Exception:
                                pass
                        sensor, retry_at = None, time.monotonic() + 5
                except Exception as exc:
                    state, error = "retrying", str(exc)
                    node.get_logger().error(error)
                    if sensor is not None:
                        try:
                            sensor.disconnect()
                        except Exception:
                            pass
                    sensor, retry_at = None, time.monotonic() + 5
            if tick - last_status >= 1:
                if state == "streaming" and time.monotonic() - last_good > 0.5:
                    state = "stale"
                for s in sides:
                    pubs[s, "status"].publish(String(data=json.dumps({"state": state, "error": error,
                        "host_timestamp_ns": time.time_ns(), "seconds_since_complete_frame": time.monotonic() - last_good,
                        "dropped_incomplete_frames": dropped})))
                last_status = tick
            rclpy.spin_once(node, timeout_sec=max(0.0, 1 / tac["fps"] - (time.monotonic() - tick)))
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if sensor is not None:
            try:
                sensor.disconnect()
            except Exception:
                pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
