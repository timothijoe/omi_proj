"""Strict, portable configuration and an explicit sensor-only topic allowlist."""

import json
import math
from pathlib import Path
import re


def load_config(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if value.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    _keys(value, {"schema_version", "domain_id", "realsense", "tactile"})
    _int(value["domain_id"], 0, 232, "domain_id")
    camera, tactile = value["realsense"], value["tactile"]
    _keys(camera, {"enabled", "serial", "color_profile", "enable_depth", "depth_profile", "align_depth"})
    _keys(tactile, {"enabled", "sdk_root", "sdk_python", "host", "pc_host", "fps", "enable_depth", "enable_wrench", "sensors"})
    for obj, names in ((camera, ("enabled", "enable_depth", "align_depth")),
                       (tactile, ("enabled", "enable_depth", "enable_wrench"))):
        for name in names:
            if type(obj[name]) is not bool:
                raise ValueError(name + " must be a JSON boolean")
    for name in ("color_profile", "depth_profile"):
        if not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*x[1-9][0-9]*", camera[name]):
            raise ValueError("profile must be WIDTHxHEIGHTxFPS")
    if camera["align_depth"] and not camera["enable_depth"]:
        raise ValueError("align_depth requires enable_depth")
    if not isinstance(camera["serial"], str):
        raise ValueError("camera serial must be a string")
    for name in ("sdk_root", "sdk_python", "host", "pc_host"):
        if not isinstance(tactile[name], str):
            raise ValueError(name + " must be a string")
    if not re.fullmatch(r"3\.[0-9]+", tactile["sdk_python"]):
        raise ValueError("sdk_python must declare the vendor Python major.minor")
    _int(tactile["fps"], 1, 120, "fps")
    _keys(tactile["sensors"], {"a", "b"})
    for sensor in tactile["sensors"].values():
        _keys(sensor, {"dev_id", "port", "pc_port", "serial", "physical_side"})
        _int(sensor["port"], 1, 65535, "port")
        _int(sensor["pc_port"], 1, 65535, "pc_port")
        if not isinstance(sensor["dev_id"], (int, str)) or isinstance(sensor["dev_id"], bool):
            raise ValueError("dev_id must be integer or string")
    if len({s["pc_port"] for s in tactile["sensors"].values()}) != 2:
        raise ValueError("A/B must use distinct local UDP ports")
    if tactile["sdk_root"]:
        root = Path(tactile["sdk_root"]).expanduser()
        tactile["sdk_root"] = str((path.parent / root).resolve())
    return value


def _keys(obj, keys):
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ValueError("configuration keys must be exactly: " + ", ".join(sorted(keys)))


def _int(value, lower, upper, name):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("%s must be integer %d..%d" % (name, lower, upper))


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("rate/duration must be finite and positive")
    return value


def sensor_topics(config):
    topics = []
    camera, tactile = config["realsense"], config["tactile"]
    if camera["enabled"]:
        topics += ["/camera/camera/color/image_raw", "/camera/camera/color/camera_info"]
        if camera["enable_depth"]:
            topics += ["/camera/camera/depth/image_rect_raw", "/camera/camera/depth/camera_info"]
        if camera["align_depth"]:
            topics += ["/camera/camera/aligned_depth_to_color/image_raw",
                       "/camera/camera/aligned_depth_to_color/camera_info"]
    if tactile["enabled"]:
        kinds = ["raw", "infer", "deformation", "shear", "metadata", "status"]
        if tactile["enable_depth"]:
            kinds.append("depth")
        if tactile["enable_wrench"]:
            kinds.append("wrench")
        topics += ["/omi/tactile/%s/%s" % (side, kind) for side in ("a", "b") for kind in kinds]
    return topics


def replay_topics(config, available):
    allowed = set(sensor_topics(config))
    if config["tactile"]["enabled"]:
        kinds = ["raw"]
        if config["tactile"]["enable_depth"]:
            kinds.append("depth")
        if config["tactile"]["enable_wrench"]:
            kinds.append("force")
        allowed.update("/tj/dm_sensor/" + side + "_" + kind for side in ("a", "b") for kind in kinds)
    if config["realsense"]["enabled"]:
        allowed.update(("/tj/dm_sensor/camera/color", "/tj/dm_sensor/camera/camera_info"))
    return sorted(set(available).intersection(allowed))


def camera_command(config):
    c = config["realsense"]
    params = {"camera_namespace": "camera", "camera_name": "camera", "enable_color": True,
              "enable_depth": c["enable_depth"], "enable_infra1": False, "enable_infra2": False,
              "enable_gyro": False, "enable_accel": False,
              "rgb_camera.color_profile": c["color_profile"],
              "depth_module.depth_profile": c["depth_profile"], "align_depth.enable": c["align_depth"]}
    if c["serial"]:
        params["serial_no"] = "'" + c["serial"] + "'"
    return ["ros2", "launch", "realsense2_camera", "rs_launch.py"] + [
        key + ":=" + (str(val).lower() if isinstance(val, bool) else val) for key, val in params.items()]
