"""Opt-in arm-only RViz replay. No hardware, control topics, or tool TCP claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np

from .robot_state_panel import Timeline

JOINTS = [f"{side}_joint{i}" for side in ("left", "right") for i in range(1, 8)]
PREFIX = "omi_replay_"
NS = "/omi/replay_3d"


def vector(value, count):
    values = np.fromstring(value, sep=" ")
    if values.shape != (count,) or not np.isfinite(values).all():
        raise ValueError("Invalid model vector: " + value)
    return values


def origin(element):
    """Known source model uses local xyz and wxyz quaternion, radians/metres."""
    if any(key in element.attrib for key in ("euler", "axisangle", "xyaxes", "zaxis", "fromto")):
        raise ValueError("Only explicit quaternion/position origins are supported")
    xyz = vector(element.get("pos", "0 0 0"), 3)
    quat = vector(element.get("quat", "1 0 0 0"), 4)
    if np.linalg.norm(quat) == 0:
        raise ValueError("Zero quaternion")
    w, x, y, z = quat / np.linalg.norm(quat)
    roll = math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y))
    pitch = math.asin(float(np.clip(2*(w*y-z*x), -1, 1)))
    yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
    return {"xyz": " ".join(f"{v:.17g}" for v in xyz),
            "rpy": " ".join(f"{v:.17g}" for v in (roll, pitch, yaw))}


def build_urdf(scene):
    """Convert this project's explicit arm chain, not arbitrary MJCF.

    Excludes scene props, attached hands and knives. Rejects unsupported arm
    transforms/joints rather than silently creating different kinematics.
    """
    scene = Path(scene).resolve()
    root = ET.parse(scene).getroot()
    compiler = root.find("compiler")
    if compiler is None or compiler.get("angle") != "radian" or compiler.get("meshdir"):
        raise ValueError("Expected explicit radian scene without compiler meshdir")
    base = root.find("worldbody/body[@name='robot_base']")
    if base is None:
        raise ValueError("Missing robot_base")
    mesh_defs = {m.get("name"): m for m in root.findall("asset/mesh")}
    robot = ET.Element("robot", name="omi_recorded_dual_arm_visual_only")
    ET.SubElement(robot, "link", name=PREFIX + "world")
    meshes, limits, seen = set(), {}, set()

    def add_body(body, parent):
        name = body.get("name")
        if name in seen:
            raise ValueError("Duplicate robot body")
        seen.add(name)
        link = ET.SubElement(robot, "link", name=PREFIX + name)
        joints = body.findall("joint")
        if len(joints) > 1 or body.find("freejoint") is not None:
            raise ValueError("Unsupported multi/free joint")
        source_joint = joints[0] if joints else None
        if source_joint is not None:
            joint_name = source_joint.get("name")
            if joint_name not in JOINTS or source_joint.get("type", "hinge") != "hinge":
                raise ValueError("Unsupported arm joint")
            if np.any(vector(source_joint.get("pos", "0 0 0"), 3)) or float(source_joint.get("ref", 0)) != 0:
                raise ValueError("Nonzero joint offset/ref needs explicit conversion")
            joint = ET.SubElement(robot, "joint", name=joint_name, type="revolute")
            lo, hi = vector(source_joint.get("range", ""), 2)
            axis = vector(source_joint.get("axis", "0 0 1"), 3)
            if np.linalg.norm(axis) == 0 or lo >= hi:
                raise ValueError("Invalid joint axis/limits")
            ET.SubElement(joint, "axis", xyz=" ".join(map(str, axis / np.linalg.norm(axis))))
            ET.SubElement(joint, "limit", lower=str(lo), upper=str(hi), effort="0", velocity="0")
            limits[joint_name] = [float(lo), float(hi)]
        else:
            joint = ET.SubElement(robot, "joint", name=name + "_fixed", type="fixed")
        ET.SubElement(joint, "parent", link=PREFIX + parent)
        ET.SubElement(joint, "child", link=PREFIX + name)
        ET.SubElement(joint, "origin", **origin(body))
        for geom in body.findall("geom"):
            if geom.get("type") != "mesh":
                raise ValueError("Expected explicit mesh-only arm visuals")
            mesh = mesh_defs[geom.get("mesh")]
            if any(k not in ("name", "file", "scale", "content_type") for k in mesh.attrib):
                raise ValueError("Unsupported mesh transform")
            path = (scene.parent / mesh.attrib["file"]).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            meshes.add(path)
            visual = ET.SubElement(link, "visual")
            ET.SubElement(visual, "origin", **origin(geom))
            geometry = ET.SubElement(visual, "geometry")
            scale = vector(mesh.get("scale", "1 1 1"), 3)
            ET.SubElement(geometry, "mesh", filename=path.as_uri(), scale=" ".join(map(str, scale)))
            material = ET.SubElement(visual, "material", name=name + "_material_" + str(len(link)))
            ET.SubElement(material, "color", rgba=geom.get("rgba", "0.8 0.8 0.8 1"))
        # Only the actual fourteen arm links. Do not import unrelated task tools.
        for child in body.findall("body"):
            if child.get("name") in {f"{s}_link{i}" for s in ("left", "right") for i in range(1, 8)}:
                add_body(child, name)
    add_body(base, "world")
    if set(limits) != set(JOINTS):
        raise ValueError("Missing one or more of the fourteen arm joints")
    ET.indent(robot)
    return ET.tostring(robot, encoding="unicode"), limits, sorted(meshes)


def prepare_model(scene, output):
    import yaml
    scene, output = Path(scene).resolve(), Path(output)
    urdf, limits, meshes = build_urdf(scene)
    signature = dict(scene=str(scene), scene_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),
                     urdf_sha256=hashlib.sha256(urdf.encode()).hexdigest(),
                     meshes=[str(p) for p in meshes], joint_order=JOINTS, limits=limits,
                     assumptions="L/R array order; radians; model uncalibrated; no gripper, body/head or tool TCP")
    dest = output / signature["urdf_sha256"][:20]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "arms.urdf").write_text(urdf)
    (dest / "model.json").write_text(json.dumps(signature, indent=2))
    (dest / "publisher.yaml").write_text(yaml.safe_dump({"/**": {"ros__parameters": {
        "robot_description": urdf, "publish_frequency": 30.0, "use_sim_time": False}}}))
    return dest.resolve()


class ReplayPose:
    def __init__(self, timeline, limits):
        self.timeline, self.limits = timeline, limits
        self.stamp, self.progressed = 0, None

    def update(self, stamp, now):
        if stamp <= 0:
            return
        if stamp != self.stamp:
            self.progressed = now
        self.stamp = stamp

    def sample(self, now):
        if self.progressed is None:
            return None, {"state": "WAITING", "reason": "No observation reference"}
        item, state, age = self.timeline.at("feedback", self.stamp)
        status = dict(state=state, reference_ns=self.stamp, source_ns=None if item is None else item["stamp"],
                      source_clock=None if item is None else item["clock"], lag_s=age,
                      reference_age_s=max(0, now-self.progressed),
                      assumptions="rad; L1..L7,R1..R7; model not calibrated; no physical TCP")
        if now-self.progressed > .5:
            status["state"] = "STALE_OR_PAUSED"
        if item is None:
            return None, status
        q = np.asarray(item["values"]["positions"], dtype=float)
        if q.shape != (14,) or not np.isfinite(q).all():
            status["state"] = "INVALID"
            return None, status
        status["out_of_model_limits"] = [name for name, v in zip(JOINTS, q)
                                         if not self.limits[name][0] <= v <= self.limits[name][1]]
        if status["out_of_model_limits"] and status["state"] == "VALID":
            status["state"] = "MODEL_LIMIT_WARNING"
        # Hold last visual pose during stale periods but explicitly flag it.
        return q.tolist(), status


def run(timeline_file, model_file):
    import rclpy
    from rclpy._rclpy_pybind11 import RCLError
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import String
    from visualization_msgs.msg import Marker
    state = ReplayPose(Timeline(json.loads(Path(timeline_file).read_text())["records"]),
                       json.loads(Path(model_file).read_text())["limits"])
    rclpy.init()
    node = rclpy.create_node("robot_replay_3d", namespace=NS)
    joint_pub = node.create_publisher(JointState, NS + "/joint_states", 2)
    status_pub = node.create_publisher(String, NS + "/status", 2)
    marker_pub = node.create_publisher(Marker, NS + "/notice", 2)
    def receive(msg):
        state.update(msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec, time.monotonic())
    node.create_subscription(Image, "/omi/observation_robot/dashboard", receive,
                             QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    def tick():
        positions, status = state.sample(time.monotonic())
        now = node.get_clock().now().to_msg()
        if positions is not None:
            msg = JointState()
            msg.header.stamp, msg.name, msg.position = now, JOINTS, positions
            joint_pub.publish(msg)
        status_pub.publish(String(data=json.dumps(status)))
        marker = Marker()
        marker.header.frame_id, marker.header.stamp = PREFIX + "world", now
        marker.ns, marker.id, marker.type, marker.action = "replay_notice", 0, Marker.TEXT_VIEW_FACING, Marker.ADD
        marker.pose.position.z = 1.35
        marker.pose.orientation.w = 1.0
        marker.scale.z = .035
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = 1.0, .75, .2, 1.0
        marker.text = ("BAG REPLAY / " + status["state"] + "\n"
                       "Arms only; rad + L/R mapping assumed\n"
                       "Uncalibrated model; NO gripper/TCP")
        marker_pub.publish(marker)
    node.create_timer(.1, tick)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("scene", type=Path)
    prep.add_argument("output", type=Path)
    view = sub.add_parser("view")
    view.add_argument("timeline", type=Path)
    view.add_argument("model", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(prepare_model(args.scene, args.output))
    else:
        run(args.timeline, args.model)


if __name__ == "__main__":
    main()
