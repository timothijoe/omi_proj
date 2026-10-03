"""SDK adapter. Importing this module never imports the vendor or opens hardware."""

import hashlib
import os
from pathlib import Path
import sys
import time

import numpy as np


class IncompleteFrame(ValueError):
    pass


def sdk_check(config):
    expected = config["sdk_python"]
    actual = "%d.%d" % sys.version_info[:2]
    if expected != actual:
        raise RuntimeError("SDK declares Python %s; ROS process uses %s. Obtain a matching SDK; do not mix ROS ABIs." % (expected, actual))
    root = Path(config["sdk_root"])
    if not config["sdk_root"] or not (root / "dmrobotics" / "__init__.py").is_file():
        raise RuntimeError("sdk_root must contain vendor dmrobotics/__init__.py")
    return root


def sdk_digest(root):
    digest = hashlib.sha256()
    for path in sorted((root / "dmrobotics").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(root)).encode())
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def connect(config, side):
    root = sdk_check(config)
    if not config["host"] or not config["pc_host"]:
        raise ValueError("configure tactile host and reachable pc_host before live acquisition")
    sys.path.insert(0, str(root))
    for key in ("NO_PROXY", "no_proxy"):
        os.environ[key] = ",".join(filter(None, [os.environ.get(key, ""), config["host"]]))
    from dmrobotics import Sensor, SensorOptions, Mode
    sensor = config["sensors"][side]
    return Sensor(SensorOptions(
        dev_id=sensor["dev_id"], backend="Flux", mode=Mode.STANDARD,
        show_fps=False, max_fps=config["fps"], enable_raw=True,
        enable_deformation=True, enable_shear=True, enable_depth=config["enable_depth"],
        enable_force=config["enable_wrench"], remote_addr="%s:%d" % (config["host"], sensor["port"]),
        pc_host=config["pc_host"], pc_port=sensor["pc_port"],
    ))


def normalize_wrench(result, frame_id):
    """Accept vendor unframed six-vectors without inventing a device frame ID."""
    framed = isinstance(result, (tuple, list)) and len(result) == 2
    if framed:
        if not isinstance(result[0], (int, np.integer)) or result[0] != frame_id:
            return None, 'frame_id_mismatched_omitted'
        result = result[1]
    try:
        value = np.asarray(result, dtype=np.float64)
    except (TypeError, ValueError):
        return None, 'invalid_shape_or_values_omitted'
    if value.shape not in ((6,), (1, 6), (6, 1)) or not np.isfinite(value).all():
        return None, 'invalid_shape_or_values_omitted'
    state = 'frame_id_matched_units_unverified' if framed else 'unframed_host_read_unsynchronized'
    return value.reshape(6).copy(), state


def snapshot(sensor, depth=False, wrench=False):
    """Reject cross-frame getter races, missing fields and nonfinite arrays.

    There is no atomic vendor snapshot API. Copies are made immediately, then all
    field frame IDs must agree. Unframed wrench is labeled unsynchronized.
    Timestamp is host receive time, NOT a device exposure timestamp.
    """
    methods = {"raw": "getRawImg", "infer": "getInferImg", "deformation": "getDeformation2D", "shear": "getShear"}
    if depth:
        methods["depth"] = "getDepth"
    arrays, ids = {}, []
    for kind, method in methods.items():
        result = getattr(sensor, method)()
        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise IncompleteFrame(kind + " has no frame ID")
        fid, value = result
        value = getattr(value, "img", value)
        if value is None or not isinstance(fid, (int, np.integer)) or fid < 0:
            raise IncompleteFrame(kind + " is missing")
        array = np.array(value, copy=True)
        if array.size == 0 or not np.isfinite(array).all():
            raise IncompleteFrame(kind + " empty/nonfinite")
        if kind in ("raw", "infer"):
            if array.dtype != np.uint8 or not (array.ndim == 2 or (array.ndim == 3 and array.shape[2] in (3, 4))):
                raise IncompleteFrame(kind + " must be mono8/BGR8/BGRA8")
        else:
            if array.dtype.kind != "f" or (kind == "depth" and array.ndim != 2) or (
                kind != "depth" and (array.ndim != 3 or array.shape[2] != 2)
            ):
                raise IncompleteFrame(kind + " has invalid shape/dtype")
            array = array.astype(np.float32)
            if not np.isfinite(array).all():
                raise IncompleteFrame(kind + " exceeds float32 range")
        arrays[kind] = array
        ids.append(int(fid))
    if len(set(ids)) != 1:
        raise IncompleteFrame("SDK getters returned different frame IDs: " + str(ids))
    if arrays["deformation"].shape != arrays["shear"].shape:
        raise IncompleteFrame("deformation/shear geometry differs")
    wrench_state = "disabled"
    if wrench:
        value, wrench_state = normalize_wrench(sensor.getForce(), ids[0])
        if value is not None:
            arrays['wrench'] = value
    return ids[0], time.time_ns(), arrays, wrench_state
