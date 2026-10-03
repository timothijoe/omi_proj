"""Opt-in, visual-only review of the supplied Marvin Stand URDF archive."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import xml.etree.ElementTree as ET

from .robot_replay_3d import JOINTS, PREFIX


def archive_assets(path):
    """Read only URDF/STL entries using system libarchive; never execute assets."""
    lib = C.CDLL("libarchive.so.13")
    declarations = {
        "archive_read_new": ([], C.c_void_p),
        "archive_read_support_filter_all": ([C.c_void_p], C.c_int),
        "archive_read_support_format_all": ([C.c_void_p], C.c_int),
        "archive_read_open_filename": ([C.c_void_p, C.c_char_p, C.c_size_t], C.c_int),
        "archive_read_next_header": ([C.c_void_p, C.POINTER(C.c_void_p)], C.c_int),
        "archive_entry_pathname": ([C.c_void_p], C.c_char_p),
        "archive_entry_filetype": ([C.c_void_p], C.c_uint),
        "archive_read_data": ([C.c_void_p, C.c_void_p, C.c_size_t], C.c_ssize_t),
        "archive_read_free": ([C.c_void_p], C.c_int),
    }
    for name, (args, result) in declarations.items():
        method = getattr(lib, name)
        method.argtypes, method.restype = args, result
    handle = lib.archive_read_new()
    assets = {}
    try:
        lib.archive_read_support_filter_all(handle)
        lib.archive_read_support_format_all(handle)
        if lib.archive_read_open_filename(handle, bytes(Path(path)), 10240) != 0:
            raise ValueError("Cannot open model archive")
        entry = C.c_void_p()
        while True:
            result = lib.archive_read_next_header(handle, C.byref(entry))
            if result == 1:  # ARCHIVE_EOF
                break
            if result != 0:
                raise ValueError("Invalid archive header")
            raw = lib.archive_entry_pathname(entry)
            if not raw.lower().endswith((b".urdf", b".stl")):
                continue
            name = PurePosixPath(raw.decode("utf-8"))
            if name.is_absolute() or ".." in name.parts or "\\" in str(name):
                raise ValueError("Unsafe asset path")
            if lib.archive_entry_filetype(entry) != 0o100000 or str(name) in assets:
                raise ValueError("Expected unique regular assets")
            chunks, size = [], 0
            buffer = C.create_string_buffer(65536)
            while True:
                n = lib.archive_read_data(handle, buffer, len(buffer))
                if n < 0:
                    raise ValueError("Archive decompression failed")
                if n == 0:
                    break
                size += n
                if size > 128 * 1024**2:
                    raise ValueError("Asset too large")
                chunks.append(buffer.raw[:n])
            assets[str(name)] = b"".join(chunks)
            if sum(map(len, assets.values())) > 256 * 1024**2:
                raise ValueError("Model archive too large")
    finally:
        lib.archive_read_free(handle)
    return assets


def convert(urdf, assets):
    """Preserve all joint origins/axes; rename only for existing replay messages."""
    robot = ET.fromstring(urdf)
    mapping = {"ZJ_Robot_link": PREFIX + "robot_base"}
    for letter, side in (("L", "left"), ("R", "right")):
        mapping.update({f"Arm_{letter}{i}_Link": PREFIX + f"{side}_link{i}" for i in range(1, 8)})
    if {x.get("name") for x in robot.findall("link")} != set(mapping):
        raise ValueError("Expected exact Marvin Stand link set")
    joints = robot.findall("joint")
    expected = {f"Arm_{s}{i}_Joint" for s in "LR" for i in range(1, 8)}
    if {j.get("name") for j in joints} != expected or len(joints) != 14:
        raise ValueError("Expected fourteen Stand joints")
    cleanups = []
    for element in robot.iter():
        for attr in ("text", "tail"):
            value = getattr(element, attr)
            if value and value.strip():
                cleanups.append(value.strip())
                setattr(element, attr, None)
    for link in robot.findall("link"):
        link.set("name", mapping[link.get("name")])
    limits = {}
    for joint in joints:
        original = joint.get("name")
        side = "left" if original[4] == "L" else "right"
        index = int(original[5])
        name = f"{side}_joint{index}"
        parent = "ZJ_Robot_link" if index == 1 else f"Arm_{original[4]}{index-1}_Link"
        child = f"Arm_{original[4]}{index}_Link"
        if (joint.get("type") != "revolute" or joint.find("parent").get("link") != parent
                or joint.find("child").get("link") != child):
            raise ValueError("Unexpected Stand joint chain")
        joint.set("name", name)
        for tag in ("parent", "child"):
            node = joint.find(tag)
            node.set("link", mapping[node.get("link")])
        limits[name] = [float(joint.find("limit").get(k)) for k in ("lower", "upper")]
    for mesh in robot.findall(".//mesh"):
        source = mesh.get("filename")
        key = source.removeprefix("package://")
        if not source.startswith("package://") or key not in assets:
            raise ValueError("Missing archive mesh: " + source)
        mesh.set("filename", Path(assets[key]).as_uri())
    ET.SubElement(robot, "link", name=PREFIX + "world")
    fixed = ET.SubElement(robot, "joint", name="stand_review_root", type="fixed")
    ET.SubElement(fixed, "parent", link=PREFIX + "world")
    ET.SubElement(fixed, "child", link=PREFIX + "robot_base")
    ET.SubElement(fixed, "origin", xyz="0 0 0", rpy="0 0 0")
    ET.indent(robot)
    return ET.tostring(robot, encoding="unicode"), limits, cleanups


LEGACY_AXIS_SIGNS = {"left": (1, 1, -1, -1, 1, -1, 1),
                     "right": (1, 1, -1, -1, -1, 1, 1)}


def legacy_axis_mapping(text):
    """Express Stand joint angles in the legacy replay convention, no TCP fit.

    A reversible reparameterization q_stand = sign * q_replay. Transform limits
    too; their agreement with the real robot is NOT established by this mapping.
    """
    root = ET.fromstring(text)
    for side, signs in LEGACY_AXIS_SIGNS.items():
        for i, sign in enumerate(signs, 1):
            if sign == 1:
                continue
            joint = root.find(f"joint[@name='{side}_joint{i}']")
            axis = joint.find("axis")
            axis.set("xyz", " ".join(str(-float(v)) for v in axis.get("xyz").split()))
            limit = joint.find("limit")
            lower, upper = float(limit.get("lower")), float(limit.get("upper"))
            limit.set("lower", str(-upper)); limit.set("upper", str(-lower))
    return ET.tostring(root, encoding="unicode")


def prepare(archive, output, rviz_template, corrected=False):
    import yaml
    assets = archive_assets(archive)
    urdfs = [k for k in assets if k.lower().endswith(".urdf")]
    if len(urdfs) != 1:
        raise ValueError("Expected one URDF")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="stand-", dir=output))
    paths = {}
    for name, data in assets.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        paths[name] = target
    text, limits, cleanups = convert(assets[urdfs[0]], paths)
    if corrected:
        text = legacy_axis_mapping(text)
        limits = {j.get("name"): [float(j.find("limit").get(k)) for k in ("lower", "upper")]
                  for j in ET.fromstring(text).findall("joint") if j.get("type") == "revolute"}
    (dest / "arms.urdf").write_text(text)
    (dest / "publisher.yaml").write_text(yaml.safe_dump({"/**": {"ros__parameters": {
        "robot_description": text, "publish_frequency": 30.0, "use_sim_time": False}}}))
    (dest / "model.json").write_text(json.dumps(dict(
        source=str(Path(archive).resolve()), source_sha256=hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
        joint_order=JOINTS, limits=limits, removed_stray_text=cleanups,
        legacy_axis_signs=LEGACY_AXIS_SIGNS if corrected else None,
        assumption="Recorded base_link = ZJ_Robot_link, unverified; no TCP; raw L/R radian joint mapping",
    ), indent=2))
    config = yaml.safe_load(Path(rviz_template).read_text())
    manager = config["Visualization Manager"]
    manager["Displays"][1]["Name"] = "NEW Stand URDF - mapping UNVERIFIED"
    if corrected:
        manager["Displays"][1]["Name"] = "Stand AXIS-CORRECTED / TCP uncalibrated"
    manager["Displays"].append({"Class": "rviz_default_plugins/MarkerArray", "Name": "L7 origin NOT TCP",
        "Enabled": True, "Value": True, "Topic": {"Value": "/omi/stand_review/markers",
        "Depth": 1, "Reliability Policy": "Reliable", "Durability Policy": "Volatile"}})
    manager["Views"]["Current"]["Focal Point"]["Z"] = .85
    (dest / "review.rviz").write_text(yaml.safe_dump(config))
    return dest


def markers(hybrid=False, corrected=False):
    import rclpy
    from visualization_msgs.msg import Marker, MarkerArray
    from geometry_msgs.msg import Point
    rclpy.init()
    node = rclpy.create_node("stand_review_labels")
    pub = node.create_publisher(MarkerArray, "/omi/stand_review/markers", 1)
    def tick():
        array = MarkerArray()
        for i in range(3):
            m = Marker()
            m.header.frame_id = PREFIX + "left_link7"
            # Link-attached labels use latest TF, not a future timestamp relative
            # to the independent 10 Hz joint replay publisher.
            m.ns, m.id, m.type = "L7_axes", i, Marker.ARROW
            m.pose.orientation.w = 1.
            m.scale.x, m.scale.y, m.scale.z = .004, .009, .015
            m.color.r, m.color.g, m.color.b = [float(i == j) for j in range(3)]
            m.color.a = 1.
            xyz = [0., 0., 0.]; xyz[i] = .06
            m.points = [Point(), Point(x=xyz[0], y=xyz[1], z=xyz[2])]
            array.markers.append(m)
        for i, (frame, z, text) in enumerate([
            ("left_link7", .09, "URDF L7 origin (NOT flange/TCP)"),
            ("world", 1.6, ("HYBRID VISUAL REVIEW / NO CONTROL\nLegacy joint chain UNCHANGED; new mesh fit only\nL5/L7 may retain old mesh; EEF alignment UNVERIFIED"
                              if hybrid else "STAND MODEL REVIEW / NO CONTROL\nbase_link = ZJ_Robot_link: UNVERIFIED\nFloating axes: recorded EEF; no fitted offset")),
        ]):
            if corrected and frame == "world":
                text = ("AXIS-CORRECTED STAND / NO CONTROL\nL3,L4,L6 and R3,R4,R5 reversed\nRoot/TCP/limits still unverified; NO fitted TCP")
            m = Marker(); m.header.frame_id = PREFIX + frame
            m.ns, m.id, m.type = "stand_notice", i, Marker.TEXT_VIEW_FACING
            m.pose.orientation.w = 1.; m.pose.position.z = z
            m.scale.z = .025; m.color.r = m.color.g = m.color.a = 1.
            m.text = text; array.markers.append(m)
        pub.publish(array)
    node.create_timer(.1, tick)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("archive"); p.add_argument("output"); p.add_argument("rviz_template")
    p.add_argument("--corrected", action="store_true")
    p = sub.add_parser("markers")
    p.add_argument("--hybrid", action="store_true")
    p.add_argument("--corrected", action="store_true")
    args = parser.parse_args()
    if args.mode == "prepare":
        print(prepare(args.archive, args.output, args.rviz_template, args.corrected))
    else:
        markers(args.hybrid, args.corrected)


if __name__ == "__main__":
    main()
