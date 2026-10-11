#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手眼标定脚本（eye-to-hand 眼在手外）
====================================
相机（Intel RealSense D435）固定不动，AprilTag 标记板装在机械臂末端。
一页上有两组 marker（45mm 外框 tag ID 0-3、50mm 外框 tag ID 4-7，tag 位图均 20mm），
通过 ROS 2 订阅彩色图像和 CameraInfo，对两组 marker 定位（PnP + 可选深度交叉验证），
分别计算每组 marker 中心到相机光学中心的距离，
并结合机械臂末端位姿，分别解出每组对应的 相机→机械臂基座 外参 T_base_cam。

使用流程：
  1. 把 apriltag_45_50mm_A4.pdf 里的任意一组（45mm + 50mm 两个 marker）
     1:1 打印，裁下贴到机械臂末端（尽量平整）。
     板面坐标系：各 marker 几何中心为原点，+x 右，+y 上（正对板子看），
     +z 垂直板面朝外。
  2. 运行本脚本，画面中应能检测到两组 marker 的 tag 并显示位姿与到光学中心的距离。
  3. 机械臂挪到不同位姿（重点：姿态要多变，俯仰/偏航各倾斜 15~30 度），
     在图像窗口按 s 采集一个样本（两组 marker 同时记录），采 15~25 个。
  4. 按 c 解算并保存结果（每组 marker 各一份 YAML + JSON）。

按键（鼠标点一下图像窗口再按）：
  s = 采集样本    d = 删除上一个样本    c = 解算并保存
  q / ESC = 退出

运行示例（Jetson, ROS2）：
  python3 hand_eye_calibration.py --ros2 \
      --base-frame base_link --ee-frame tool0
  # 仅查看/保存 marker 在彩色相机光学坐标系下的位姿：
  python3 hand_eye_calibration.py --cam-only
  # SSH 无图形界面：每 2 秒自动记录一次；可用 Ctrl+C 退出
  python3 hand_eye_calibration.py --cam-only --headless
  # 仅保存 10 个样本后退出：
  python3 hand_eye_calibration.py --cam-only --headless --max-samples 10
运行示例（ROS1 仅用于末端位姿，图像仍通过 ROS 2 获取）：
  python3 hand_eye_calibration.py --ros1
没有机械臂 TF 时可手动输入末端位姿（图像仍从 ROS 2 话题获取）：
  python3 hand_eye_calibration.py --manual
只计算 T_cam_board（不接机械臂、不输位姿，逐样本保存板在相机系的位姿）：
  python3 hand_eye_calibration.py --cam-only
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

# ---------------- 板子参数（与 AprilTagGenerator.py 对应） ----------------
# 每组 marker：(外框边长mm, tag位图边长mm, tag ID列表)
# ID 顺序对应板角：左下, 右下, 左上, 右上
BOARDS = [
    (45.0, 20.0, [0, 1, 2, 3]),
    (50.0, 20.0, [4, 5, 6, 7]),
]
TAG_FAMILY_DICT = cv2.aruco.DICT_APRILTAG_36H11   # tag36h11


def build_board_object_points(region_mm: float, tag_mm: float, tag_ids):
    """
    构建四角 tag 板的 3D 点（板坐标系：marker 中心为原点，+x 右，+y 上，+z 朝外）。
    返回单位为米的 obj_points (N,3) 和 tag_id -> (4,3) 角点字典。
    """
    s = tag_mm                          # tag 边长 mm
    H = region_mm / 2.0
    off = H - s / 2.0                   # tag 中心到板中心的偏移
    centers = {                         # 与生成脚本 CORNER_POSITIONS 对应
        tag_ids[0]: (-off, -off),   # 左下
        tag_ids[1]: (+off, -off),   # 右下
        tag_ids[2]: (-off, +off),   # 左上
        tag_ids[3]: (+off, +off),   # 右上
    }
    obj_points = []
    tag_corners = {}                    # tag_id -> (4,3)
    for tid, (cx, cy) in centers.items():
        # 板坐标系中的几何角点：左上、右上、右下、左下。
        # 图案编码方向由 detect_all_boards 的两种角点顺序判定。
        corners = np.array([
            [cx - s / 2, cy + s / 2, 0],
            [cx + s / 2, cy + s / 2, 0],
            [cx + s / 2, cy - s / 2, 0],
            [cx - s / 2, cy - s / 2, 0],
        ], dtype=np.float32)
        corners *= 0.001  # PnP 平移与机械臂 TF 均使用米
        tag_corners[tid] = corners
        obj_points.append(corners)
    return np.vstack(obj_points).astype(np.float32), tag_corners


# ---------------- 小工具 ----------------
def quat_to_R(x, y, z, w):
    """四元数 -> 3x3 旋转矩阵"""
    n = np.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def rpy_deg(R):
    """旋转矩阵 -> ZYX 欧拉角（roll/pitch/yaw，度）"""
    sy = -R[2, 0]
    if abs(sy) < 1.0 - 1e-8:
        roll = np.degrees(np.arctan2(R[2, 1], R[2, 2]))
        pitch = np.degrees(np.arcsin(sy))
        yaw = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    else:  # 万向锁
        roll = np.degrees(np.arctan2(-R[1, 2], R[1, 1]))
        pitch = np.degrees(np.pi / 2 * np.sign(sy))
        yaw = 0.0
    return roll, pitch, yaw


def T_of(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t).reshape(3)
    return T


def inv_T(T):
    Ti = np.eye(4)
    Ti[:3, :3] = T[:3, :3].T
    Ti[:3, 3] = -T[:3, :3].T @ T[:3, 3]
    return Ti


def rvec_tvec_to_T(rvec, tvec):
    R, _ = cv2.Rodrigues(np.asarray(rvec).reshape(3, 1))
    return T_of(R, np.asarray(tvec).reshape(3))


def mean_rotation(Rs):
    """多个旋转矩阵的平均（SVD 投影到 SO(3)）"""
    M = np.mean(Rs, axis=0)
    U, _, Vt = np.linalg.svd(M)
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    return U @ D @ Vt


def dist_to_optical_center(T_cb):
    """marker 中心到相机光学中心的欧氏距离（mm）"""
    return float(np.linalg.norm(T_cb[:3, 3]) * 1000)


def display_available():
    """在独立进程验证 HighGUI，避免 Qt 插件失败导致主进程 abort。"""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    if os.environ.get("QT_QPA_PLATFORM") in ("offscreen", "minimal", "minimalegl"):
        return False
    probe = ("import resource; resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); "
             "import cv2; cv2.namedWindow('hand-eye-display-probe'); "
             "cv2.destroyAllWindows()")
    try:
        result = subprocess.run([sys.executable, "-c", probe],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


# ---------------- ROS 2 RealSense 图像 ----------------
class ROS2Camera:
    """订阅彩色图像、对应内参和可选的对齐深度图。"""
    def __init__(self, color_topic, info_topic, depth_topic):
        import rclpy
        from cv_bridge import CvBridge
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import CameraInfo, Image

        if not rclpy.ok():
            rclpy.init()
        self._rclpy = rclpy
        self.node = rclpy.create_node("hand_eye_camera")
        self.bridge = CvBridge()
        self._condition = threading.Condition()
        self._color = None
        self._color_stamp = None
        self._depth = None
        self._depth_stamp = None
        self._sequence = 0
        self._read_sequence = 0
        self.K = None
        self.D = None
        self.frame_id = None
        self._size = None
        self.node.create_subscription(Image, color_topic, self._on_color, qos_profile_sensor_data)
        self.node.create_subscription(CameraInfo, info_topic, self._on_info, qos_profile_sensor_data)
        if depth_topic:
            self.node.create_subscription(Image, depth_topic, self._on_depth, qos_profile_sensor_data)
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self._spin = threading.Thread(target=self.executor.spin, daemon=True)
        self._spin.start()
        print(f"[相机] 彩色图像: {color_topic}; 内参: {info_topic}; "
              f"对齐深度: {depth_topic or '关闭'}")

    @staticmethod
    def _stamp_ns(msg):
        return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

    def _on_color(self, msg):
        try:
            color = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.node.get_logger().warning(f"彩色图像转换失败: {exc}")
            return
        with self._condition:
            self._color = color
            self._color_stamp = self._stamp_ns(msg)
            self._sequence += 1
            self._condition.notify_all()

    def _on_info(self, msg):
        K = np.asarray(msg.k, dtype=np.float64).reshape(3, 3)
        D = np.asarray(msg.d, dtype=np.float64)
        if (msg.distortion_model not in ("plumb_bob", "rational_polynomial")
                or not np.isfinite(K).all() or not np.isfinite(D).all()
                or K[0, 0] <= 0 or K[1, 1] <= 0):
            self.node.get_logger().warning("CameraInfo 内参或畸变模型无效")
            return
        with self._condition:
            self.K, self.D = K, D
            self._size = (msg.width, msg.height)
            self.frame_id = msg.header.frame_id
            self._condition.notify_all()

    def _on_depth(self, msg):
        if msg.encoding not in ("16UC1", "32FC1"):
            self.node.get_logger().warning(f"不支持的深度编码: {msg.encoding}")
            return
        try:
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.node.get_logger().warning(f"深度图像转换失败: {exc}")
            return
        depth = depth.astype(np.float32) * (0.001 if msg.encoding == "16UC1" else 1.0)
        with self._condition:
            self._depth = depth
            self._depth_stamp = self._stamp_ns(msg)

    def read(self, timeout=5.0):
        """取下一帧彩色图像及时间相近的对齐深度，返回 (BGR, depth_m)。"""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if (self._sequence > self._read_sequence and self.K is not None
                        and self._size == (self._color.shape[1], self._color.shape[0])):
                    self._read_sequence = self._sequence
                    depth = self._depth
                    if (depth is None or depth.shape != self._color.shape[:2]
                            or abs(self._depth_stamp - self._color_stamp) > 100_000_000):
                        depth = None
                    return self._color.copy(), depth
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("等待彩色图像及匹配的 CameraInfo 超时，请检查 ROS 2 话题")
                self._condition.wait(remaining)

    @staticmethod
    def depth_at(depth_frame, px, py, win=4):
        """取目标附近有效深度的中位数，单位 m。"""
        if depth_frame is None:
            return None
        h, w = depth_frame.shape
        x, y = int(px), int(py)
        patch = depth_frame[max(0, y-win):min(h, y+win+1),
                            max(0, x-win):min(w, x+win+1)]
        valid = patch[np.isfinite(patch) & (patch > 0.05)]
        return float(np.median(valid)) if valid.size else None

    def stop(self):
        self.executor.shutdown()
        self.node.destroy_node()
        self._spin.join(timeout=2.0)


# ---------------- 标记板检测与位姿估计 ----------------
def detect_markers(gray, detector):
    if isinstance(detector, tuple):  # OpenCV < 4.7
        return cv2.aruco.detectMarkers(gray, detector[0], parameters=detector[1])
    return detector.detectMarkers(gray)


def detect_board(color_bgr, K, D, tag_corners, detector):
    """
    检测单个 marker（按 tag_corners 里登记的 tag ID 过滤）并解算 T_cam_board。
    返回 (成功?, T(4x4)或None, 角点列表用于画图, 检测到的tag数, 重投影误差px)
    """
    return detect_all_boards(color_bgr, K, D, {0: tag_corners}, detector)[0]


def detect_all_boards(color_bgr, K, D, board_corners, detector):
    """按空间位置区分 A4 上重复的板，再分别解算两组 marker。"""
    gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
    tags, ids, _ = detect_markers(gray, detector)
    observations = []
    if ids is not None:
        for corner4, tid in zip(tags, ids.flatten()):
            observations.append((int(tid), corner4.reshape(4, 2)))

    results = {}
    for bi, tag_corners in board_corners.items():
        board_obs = [(tid, c) for tid, c in observations if tid in tag_corners]
        groups = []
        seen = set()
        for _, seed in board_obs:
            center = seed.mean(axis=0)
            seed_size = float(np.linalg.norm(seed[1] - seed[0]))
            selected = {}
            for idx, (tid, corners) in enumerate(board_obs):
                size = float(np.linalg.norm(corners[1] - corners[0]))
                distance = float(np.linalg.norm(corners.mean(axis=0) - center))
                if distance > 2.8 * max(seed_size, size):
                    continue
                if tid not in selected or distance < selected[tid][0]:
                    selected[tid] = (distance, idx)
            indices = tuple(sorted(value[1] for value in selected.values()))
            if indices and indices not in seen:
                seen.add(indices)
                groups.append({board_obs[idx][0]: board_obs[idx][1] for idx in indices})

        candidates = []
        for corners_by_id in groups:
            n_tags = len(corners_by_id)
            if n_tags < 2:
                continue
            img_pts = np.vstack([c.astype(np.float32) for c in corners_by_id.values()])
            # 当前 A4 PDF 的 tag 图案相对 OpenCV 字典旋转了 180°；
            # 同时尝试两种角点对应，兼容其他工具打印的同一 ID。
            for order in ((0, 1, 2, 3), (2, 3, 0, 1)):
                obj_pts = np.vstack([tag_corners[tid][list(order)]
                                     for tid in corners_by_id])
                try:
                    okp, rvec, tvec = cv2.solvePnP(
                        obj_pts, img_pts, K, D, flags=cv2.SOLVEPNP_ITERATIVE)
                    if not okp:
                        continue
                    rvec, tvec = cv2.solvePnPRefineLM(
                        obj_pts, img_pts, K, D, rvec, tvec)
                    if tvec[2, 0] <= 0:
                        continue
                    proj, _ = cv2.projectPoints(obj_pts, rvec, tvec, K, D)
                except cv2.error:
                    continue
                reproj = float(np.linalg.norm(
                    proj.reshape(-1, 2) - img_pts, axis=1).mean())
                if np.isfinite(reproj) and reproj <= 5.0:
                    center = np.mean([c.mean(axis=0) for c in corners_by_id.values()], axis=0)
                    center_distance = float(np.linalg.norm(
                        center - np.array([K[0, 2], K[1, 2]])))
                    candidates.append((n_tags, center_distance, reproj,
                                       rvec_tvec_to_T(rvec, tvec), corners_by_id))

        if candidates:
            n_tags, _, reproj, T, corners_by_id = min(
                candidates, key=lambda item: (-item[0], item[1], item[2]))
            results[bi] = (True, T, corners_by_id, n_tags, reproj)
        else:
            corners_by_id = max(groups, key=len, default={})
            results[bi] = (False, None, corners_by_id, len(corners_by_id), None)
    return results


# ---------------- 绘制叠加信息 ----------------
# 每组 marker 的显示颜色（BGR）
BOARD_COLORS = [(0, 255, 0), (255, 128, 0)]   # 45mm 绿, 50mm 橙


def draw_overlay(frame, board_results, depths, n_samples):
    """画各组 marker 检测结果 + 到光学中心的距离 + 状态文字"""
    for bi, (ok, T_cb, corners_by_id, n_tags, reproj) in board_results.items():
        color = BOARD_COLORS[bi % len(BOARD_COLORS)]
        if corners_by_id:
            for c2d in corners_by_id.values():
                c = c2d.astype(int)
                cv2.polylines(frame, [c.reshape(-1, 1, 2)], True, color, 2)
                for p in c:
                    cv2.circle(frame, tuple(p), 3, (0, 0, 255), -1)

    def put(txt, i, color=(255, 255, 255)):
        cv2.putText(frame, txt, (10, 25 + 22 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
        cv2.putText(frame, txt, (10, 25 + 22 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    i = 0
    for bi, (ok, T_cb, corners_by_id, n_tags, reproj) in board_results.items():
        region_mm = BOARDS[bi][0]
        color = BOARD_COLORS[bi % len(BOARD_COLORS)]
        if ok:
            d_opt = dist_to_optical_center(T_cb)
            xyz = T_cb[:3, 3] * 1000
            roll, pitch, yaw = rpy_deg(T_cb[:3, :3])
            depth_m = depths.get(bi)
            dp = f"  depth: {depth_m * 1000:.0f} mm" if depth_m else ""
            put(f"{region_mm:.0f}mm: opt.dist {d_opt:.1f} mm  "
                f"XYZ: {xyz[0]:.0f},{xyz[1]:.0f},{xyz[2]:.0f} mm", i, color); i += 1
            put(f"   RPY: {roll:.1f},{pitch:.1f},{yaw:.1f} deg  "
                f"tags {n_tags}/4  reproj {reproj:.2f}px{dp}", i, color); i += 1
        else:
            put(f"{region_mm:.0f}mm: NO marker (need >= 2 tags, "
                f"seen {n_tags})", i, (0, 0, 255)); i += 1
    put(f"samples: {n_samples}   [s]save [d]del [c]solve [q]quit", i, (0, 255, 0))
    return frame


# ---------------- 机械臂位姿读取 ----------------
class RobotPoseROS2:
    def __init__(self, base_frame, ee_frame):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from tf2_ros import Buffer, TransformListener
        if not rclpy.ok():
            rclpy.init()
        self._rclpy = rclpy
        self.node = Node("hand_eye_calib")
        self.tf = Buffer()
        TransformListener(self.tf, self.node)
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self._spin = threading.Thread(target=self.executor.spin, daemon=True)
        self._spin.start()
        self.base_frame, self.ee_frame = base_frame, ee_frame

    def get_gripper2base(self):
        tr = self.tf.lookup_transform(self.base_frame, self.ee_frame,
                                      self._rclpy.time.Time(),
                                      timeout=self._rclpy.duration.Duration(seconds=2.0))
        t = tr.transform.translation
        q = tr.transform.rotation
        return quat_to_R(q.x, q.y, q.z, q.w), np.array([t.x, t.y, t.z])


class RobotPoseROS1:
    def __init__(self, base_frame, ee_frame):
        import rospy
        import tf2_ros
        rospy.init_node("hand_eye_calib", disable_signals=True)
        self._rospy = rospy
        self.tf = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.tf)
        self.base_frame, self.ee_frame = base_frame, ee_frame

    def get_gripper2base(self):
        tr = self.tf.lookup_transform(self.base_frame, self.ee_frame,
                                      self._rospy.Time(0),
                                      timeout=self._rospy.Duration(2.0))
        t = tr.transform.translation
        q = tr.transform.rotation
        return quat_to_R(q.x, q.y, q.z, q.w), np.array([t.x, t.y, t.z])


class RobotPoseManual:
    """无 ROS 时手动输入末端位姿：x y z(m) + RPY(deg)，空格分隔"""
    def get_gripper2base(self):
        while True:
            try:
                v = input("[手动输入] x y z (m)  roll pitch yaw (deg): ").split()
                vals = [float(x) for x in v]
                assert len(vals) == 6
                x, y, z, r, p, yw = vals
                rr, pp, yy = np.radians([r, p, yw])
                Rx = np.array([[1, 0, 0], [0, np.cos(rr), -np.sin(rr)], [0, np.sin(rr), np.cos(rr)]])
                Ry = np.array([[np.cos(pp), 0, np.sin(pp)], [0, 1, 0], [-np.sin(pp), 0, np.cos(pp)]])
                Rz = np.array([[np.cos(yy), -np.sin(yy), 0], [np.sin(yy), np.cos(yy), 0], [0, 0, 1]])
                return Rz @ Ry @ Rx, np.array([x, y, z])
            except Exception:
                print("  输入格式不对，请输入 6 个数字，例如: 0.42 -0.10 0.35 10 -25 0")


def save_cam_only_sample(samples, T_by_board, reproj_by_board, n_tags_by_board,
                         depth_by_board, out_dir, camera_frame):
    """--cam-only 模式：把当前样本的两组 T_cam_board 追加保存到 JSON"""
    i = len(samples)
    samples.append(T_by_board)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "cam_only_samples.json")
    data = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    entry = {"index": i, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
             "camera_frame": camera_frame,
             "boards": {}}
    for bi, T in T_by_board.items():
        region_mm = BOARDS[bi][0]
        r, p, y = rpy_deg(T[:3, :3])
        entry["boards"][f"{region_mm:.0f}mm"] = {
            "T_cam_board": T.tolist(),
            "translation_mm": (T[:3, 3] * 1000).tolist(),
            "dist_to_optical_center_mm": dist_to_optical_center(T),
            "rpy_deg": [r, p, y],
            "reproj_px": reproj_by_board.get(bi),
            "n_tags": n_tags_by_board.get(bi),
            "depth_mm": depth_by_board[bi] * 1000 if depth_by_board.get(bi) is not None else None,
        }
    data.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    ds = ", ".join(f"{BOARDS[bi][0]:.0f}mm {dist_to_optical_center(T):.0f}mm"
                   for bi, T in T_by_board.items())
    print(f"  样本 {i + 1}: 光学中心距离 {ds} -> {path}")


def make_robot_reader(args):
    if args.manual:
        print("[机械臂] 手动输入模式")
        return RobotPoseManual()
    if args.ros2:
        try:
            r = RobotPoseROS2(args.base_frame, args.ee_frame)
            print(f"[机械臂] ROS2 TF: {args.base_frame} <- {args.ee_frame}")
            return r
        except Exception as e:
            print(f"[机械臂] ROS2 初始化失败({e})，回退到手动输入")
            return RobotPoseManual()
    if args.ros1:
        try:
            r = RobotPoseROS1(args.base_frame, args.ee_frame)
            print(f"[机械臂] ROS1 TF: {args.base_frame} <- {args.ee_frame}")
            return r
        except Exception as e:
            print(f"[机械臂] ROS1 初始化失败({e})，回退到手动输入")
            return RobotPoseManual()
    print("[机械臂] 未指定 --ros1/--ros2/--manual，尝试 ROS2...")
    return make_robot_reader(argparse.Namespace(**{**vars(args), "ros2": True}))


# ---------------- 手眼解算 ----------------
def consistency_error(X_cam2base, samples):
    """
    一致性校验：若 X 正确，则 G = inv(T_g2b) * X * T_cam2board 对所有样本
    应为同一个常量（marker 相对末端的安装位姿）。
    返回 (平均平移误差 mm, 平均旋转误差 deg, G)
    """
    Gs = []
    for R_g2b, t_g2b, T_cb in samples:
        G = inv_T(T_of(R_g2b, t_g2b)) @ X_cam2base @ T_cb
        Gs.append(G)
    G0 = Gs[len(Gs) // 2]
    terr, rerr = [], []
    for G in Gs:
        terr.append(np.linalg.norm(G[:3, 3] - G0[:3, 3]) * 1000)
        rerr.append(np.degrees(np.linalg.norm(
            cv2.Rodrigues(G[:3, :3] @ G0[:3, :3].T)[0])))
    return float(np.mean(terr)), float(np.mean(rerr)), Gs[len(Gs) // 2]


def solve_hand_eye(samples, out_dir, board_label):
    """eye-to-hand：把机械臂位姿取逆传入 calibrateHandEye，输出 candidate cam2base，
    再用一致性校验自动挑出正确解（并同时尝试其逆，防手顺搞反）。"""
    R_b2g = [R.T for R, _, _ in samples]
    t_b2g = [-R.T @ t for R, t, _ in samples]
    R_t2c = [T_cb[:3, :3] for _, _, T_cb in samples]
    t_t2c = [T_cb[:3, 3] for _, _, T_cb in samples]

    methods = {"PARK": cv2.CALIB_HAND_EYE_PARK,
               "TSAI": cv2.CALIB_HAND_EYE_TSAI,
               "HORAUD": cv2.CALIB_HAND_EYE_HORAUD,
               "DANIILIDIS": cv2.CALIB_HAND_EYE_DANIILIDIS}
    results = []
    for name, flag in methods.items():
        try:
            R_X, t_X = cv2.calibrateHandEye(R_b2g, t_b2g, R_t2c, t_t2c, method=flag)
        except cv2.error as e:
            print(f"  [{name}] 求解失败: {e}")
            continue
        for inv_tag, X in (("direct", T_of(R_X, t_X)),
                           ("inverse", inv_T(T_of(R_X, t_X)))):
            terr, rerr, _ = consistency_error(X, samples)
            results.append((terr + rerr * 2.0, name, inv_tag, X, terr, rerr))

    if not results:
        raise RuntimeError("所有方法均求解失败")
    results.sort(key=lambda r: r[0])
    print(f"\n===== [{board_label}] 各方法一致性（越小越好）=====")
    for score, name, tag, X, terr, rerr in results:
        print(f"  {name:11s}/{tag:8s}: 平移误差 {terr:6.2f} mm, 旋转误差 {rerr:6.3f} deg")

    _, name, tag, X, terr, rerr = results[0]
    print(f"\n>>> [{board_label}] 采用 {name}/{tag}: T_base_cam（相机在基座系的位姿）")
    print(np.round(X, 5))
    r, p, y = rpy_deg(X[:3, :3])
    print(f">>> 平移 (mm): {X[:3, 3] * 1000}")
    print(f">>> RPY  (deg): roll={r:.2f}, pitch={p:.2f}, yaw={y:.2f}")
    print(f">>> 校验: 平移一致性 {terr:.2f} mm, 旋转一致性 {rerr:.3f} deg")

    # 校验量 + marker 相对末端的安装位姿（一致性估计）
    terr2, rerr2, G = consistency_error(X, samples)

    # 保存
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    yaml_path = os.path.join(out_dir, f"handeye_result_{board_label}_{stamp}.yaml")
    fs = cv2.FileStorage(yaml_path, cv2.FileStorage_WRITE)
    fs.write("T_base_cam", X)                        # 相机 -> 基座
    fs.write("T_cam_base", inv_T(X))                 # 基座 -> 相机
    fs.write("T_gripper_marker", G)                  # marker 相对末端的安装位姿（校验用）
    fs.release()

    data = {
        "board": board_label,
        "method": f"{name}/{tag}",
        "T_base_cam": X.tolist(),
        "T_cam_base": inv_T(X).tolist(),
        "T_gripper_marker": G.tolist(),
        "consistency_translation_mm": terr2,
        "consistency_rotation_deg": rerr2,
        "n_samples": len(samples),
        "note": "eye-to-hand: T_base_cam = 相机在机械臂基座坐标系下的外参; "
                "T_gripper_marker = marker 在末端坐标系下的安装位姿(由一致性估计)",
    }
    json_path = os.path.join(out_dir, f"handeye_result_{board_label}_{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[{board_label}] 结果已保存:\n  {yaml_path}\n  {json_path}")
    return X


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser(description="D435 + AprilTag 双 marker eye-to-hand 手眼标定")
    ap.add_argument("--ros1", action="store_true", help="用 ROS1 TF 读取末端位姿")
    ap.add_argument("--ros2", action="store_true", help="用 ROS2 TF 读取末端位姿")
    ap.add_argument("--manual", action="store_true", help="手动输入末端位姿（调试用）")
    ap.add_argument("--cam-only", action="store_true",
                    help="只计算 T_cam_board，不读取机械臂位姿，逐样本保存")
    ap.add_argument("--base-frame", default="base_link", help="基座 TF frame")
    ap.add_argument("--ee-frame", default="tool0", help="末端 TF frame")
    ap.add_argument("--min-tags", type=int, default=2, help="每组至少检测到的 tag 数")
    ap.add_argument("--avg-frames", type=int, default=12, help="采集时平均的帧数")
    ap.add_argument("--out-dir", default="handeye_result", help="结果保存目录")
    ap.add_argument("--color-topic", default="/camera/camera/color/image_raw",
                    help="RealSense 彩色图像话题")
    ap.add_argument("--camera-info-topic", default="/camera/camera/color/camera_info",
                    help="彩色相机 CameraInfo 话题")
    ap.add_argument("--depth-topic", default="/camera/camera/aligned_depth_to_color/image_raw",
                    help="对齐到彩色图的深度话题；设为空字符串可关闭")
    ap.add_argument("--headless", action="store_true", help="不用图像窗口，在终端输出并定期保存位姿")
    ap.add_argument("--capture-interval", type=float, default=2.0,
                    help="无界面模式自动保存位姿的间隔（秒，默认 2）")
    ap.add_argument("--max-samples", type=int, default=0,
                    help="无界面模式保存多少个样本后退出；0 表示持续运行")
    args = ap.parse_args()
    if args.capture_interval <= 0 or args.max_samples < 0:
        ap.error("--capture-interval 必须大于 0，--max-samples 不能小于 0")
    headless = args.headless or not display_available()
    if headless and not args.cam_only:
        ap.error("无图形显示时请使用 --cam-only；手眼标定采样需要图像窗口")

    board_corners = {}       # board_idx -> {tag_id: (4,3)}
    for bi, (region_mm, tag_mm, tag_ids) in enumerate(BOARDS):
        _, tag_corners = build_board_object_points(region_mm, tag_mm, tag_ids)
        board_corners[bi] = tag_corners
        print(f"[板子{bi}] 外框 {region_mm} mm, tag {tag_mm} mm, ID {tag_ids}")

    aruco_dict = cv2.aruco.getPredefinedDictionary(TAG_FAMILY_DICT)
    try:  # OpenCV >= 4.7
        detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
    except AttributeError:
        detector = (aruco_dict, cv2.aruco.DetectorParameters_create())

    cam = ROS2Camera(args.color_topic, args.camera_info_topic, args.depth_topic)
    cam_only = args.cam_only
    if cam_only:
        print("[模式] --cam-only：只计算 T_cam_board，不读取机械臂位姿")
        robot = None
    else:
        robot = make_robot_reader(args)

    samples = []          # [(R_g2b, t_g2b, {board_idx: T_cam_board})]；cam-only 时存 {bi: T_cb}
    cam_only_dir = args.out_dir
    if headless:
        print(f"[无界面] 每 {args.capture_interval:g} 秒保存一次检测到的位姿；Ctrl+C 退出")
    else:
        cv2.namedWindow("hand-eye calibration", cv2.WINDOW_NORMAL)

    if headless:
        print("[无界面] 等待图像和 marker；位姿以彩色相机光学坐标系为参考")
    elif cam_only:
        print("\n开始采集。移动板子（或相机）-> 图像窗口按 s 保存当前两组 T_cam_board，"
              "按 c 查看汇总。建议先按 d 修正再继续。")
    else:
        print("\n开始采集。移动机械臂 -> 图像窗口按 s 采集。"
              "建议 15~25 个样本，姿态尽量多变（各方向倾斜 15~30 度）。")

    last_report = 0.0
    last_capture = time.monotonic()
    try:
        while True:
            try:
                color, depth = cam.read()
            except TimeoutError as exc:
                print(f"[相机] {exc}")
                break
            board_results = detect_all_boards(color, cam.K, cam.D, board_corners, detector)

            # 每组 marker 中心的深度（交叉验证用）
            depths = {}
            for bi, (ok, T_cb, corners_by_id, n_tags, reproj) in board_results.items():
                if ok:
                    cx = float(np.mean([c[:, 0].mean() for c in corners_by_id.values()]))
                    cy = float(np.mean([c[:, 1].mean() for c in corners_by_id.values()]))
                    depths[bi] = cam.depth_at(depth, cx, cy)

            if headless:
                now = time.monotonic()
                if now - last_report >= 1.0:
                    for bi, (ok, T_cb, _, n_tags, reproj) in board_results.items():
                        if ok and n_tags >= args.min_tags:
                            r, p, y = rpy_deg(T_cb[:3, :3])
                            xyz = T_cb[:3, 3] * 1000
                            print(f"[{BOARDS[bi][0]:.0f}mm] {cam.frame_id}: "
                                  f"XYZ={np.round(xyz, 1)} mm, "
                                  f"RPY={r:.1f}/{p:.1f}/{y:.1f} deg, "
                                  f"距离={dist_to_optical_center(T_cb):.1f} mm, "
                                  f"tags={n_tags}, 重投影={reproj:.2f}px", flush=True)
                        else:
                            reason = (f"仅检测到 {n_tags}/{len(board_corners[bi])} 个 tag"
                                      if n_tags < args.min_tags else "角点几何或重投影误差不合格")
                            print(f"[{BOARDS[bi][0]:.0f}mm] {reason}", flush=True)
                    last_report = now
                key = ord('s') if now - last_capture >= args.capture_interval else -1
                if key == ord('s'):
                    last_capture = now
            else:
                key = cv2.waitKey(1) & 0xFF
                frame = draw_overlay(color.copy(), board_results, depths, len(samples))

            if key in (ord('q'), 27):
                break
            elif key == ord('s'):
                # 找出当前两组中检测合格的板子
                good = {bi: res for bi, res in board_results.items()
                        if res[0] and res[3] >= args.min_tags}
                if not good:
                    if headless:
                        continue
                    print(f"  [拒绝] 没有任何一组 marker 检测到 >= {args.min_tags} 个 tag")
                    time.sleep(0.5)
                    continue
                # 多帧平均，抑制抖动（两组同时采集）
                Ts = {bi: [] for bi in good}
                for _ in range(args.avg_frames):
                    try:
                        c2, _ = cam.read()
                    except TimeoutError as exc:
                        print(f"  [采集失败] {exc}")
                        break
                    res2 = detect_all_boards(c2, cam.K, cam.D, board_corners, detector)
                    for bi in good:
                        ok2, T2, _, n2, _ = res2[bi]
                        if ok2 and n2 >= args.min_tags:
                            Ts[bi].append(T2)
                    time.sleep(0.02)
                T_avg = {}
                for bi in good:
                    if len(Ts[bi]) < max(3, args.avg_frames // 2):
                        print(f"  [警告] {BOARDS[bi][0]:.0f}mm marker 连续采集期间检测不稳定，本样本跳过该组")
                        continue
                    t_mean = np.median([T[:3, 3] for T in Ts[bi]], axis=0)
                    R_mean = mean_rotation([T[:3, :3] for T in Ts[bi]])
                    T_avg[bi] = T_of(R_mean, t_mean)
                if not T_avg:
                    print("  [拒绝] 两组 marker 均采集失败，请保持静止或改善光照")
                    continue

                if cam_only:
                    save_cam_only_sample(samples, T_avg,
                                         {bi: board_results[bi][4] for bi in T_avg},
                                         {bi: board_results[bi][3] for bi in T_avg},
                                         depths, cam_only_dir, cam.frame_id)
                    if headless and args.max_samples and len(samples) >= args.max_samples:
                        break
                    continue

                try:
                    R_g2b, t_g2b = robot.get_gripper2base()
                except Exception as e:
                    print(f"  [失败] 读取机械臂位姿失败: {e}")
                    time.sleep(0.5)
                    continue
                samples.append((R_g2b, t_g2b, T_avg))
                ds = ", ".join(f"{BOARDS[bi][0]:.0f}mm 光学中心距离 "
                               f"{dist_to_optical_center(T):.0f} mm" for bi, T in T_avg.items())
                print(f"  样本 {len(samples)}: {ds}, "
                      f"tags={[board_results[bi][3] for bi in T_avg]}, "
                      f"重投影 {[round(board_results[bi][4], 2) for bi in T_avg]}px")
            elif key == ord('d') and samples:
                if cam_only:
                    removed = samples.pop()
                    # 重写 JSON（去掉最后一条）
                    path = os.path.join(cam_only_dir, "cam_only_samples.json")
                    if os.path.exists(path):
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                        data = data[:len(samples)]
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"  已删除上一个样本，剩 {len(samples)} 个")
                else:
                    samples.pop()
                    print(f"  已删除上一个样本，剩 {len(samples)} 个")
            elif key == ord('c'):
                if cam_only:
                    print(f"\n===== cam-only 汇总（共 {len(samples)} 个样本）=====")
                    for i, T_by_board in enumerate(samples):
                        parts = []
                        for bi, T in T_by_board.items():
                            r, p, y = rpy_deg(T[:3, :3])
                            xyz = T[:3, 3] * 1000
                            parts.append(f"{BOARDS[bi][0]:.0f}mm: opt.dist "
                                         f"{dist_to_optical_center(T):.1f} mm, "
                                         f"XYZ {np.round(xyz, 1)}, RPY {r:.1f}/{p:.1f}/{y:.1f}")
                        print(f"  [{i}] " + " | ".join(parts))
                    print("结果保存在 cam_only_samples.json，按 q 退出")
                    cv2.waitKey(0)
                    continue
                if len(samples) < 5:
                    print("  [拒绝] 样本太少，至少 5 个（建议 15~25）")
                    continue
                cv2.destroyWindow("hand-eye calibration")

                # 每组 marker 分别解算手眼外参
                solved = 0
                for bi, (region_mm, tag_mm, tag_ids) in enumerate(BOARDS):
                    board_samples = [(R, t, T[bi]) for R, t, T in samples if bi in T]
                    if len(board_samples) < 5:
                        print(f"\n[{region_mm:.0f}mm] 有效样本只有 {len(board_samples)} 个（<5），跳过该组")
                        continue
                    solve_hand_eye(board_samples, args.out_dir, f"{region_mm:.0f}mm")
                    solved += 1
                if solved == 2:
                    print("\n两组 marker 外参均已解算，可互相对照验证一致性。")

                print("\n按任意键继续采集/退出...")
                cv2.waitKey(0)
                break

            if not headless:
                cv2.imshow("hand-eye calibration", frame)

    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    finally:
        cam.stop()
        if robot is not None and isinstance(robot, RobotPoseROS2):
            robot.executor.shutdown()
            robot.node.destroy_node()
            robot._spin.join(timeout=2.0)
        if cam._rclpy.ok():
            cam._rclpy.shutdown()
        if not headless:
            cv2.destroyAllWindows()
        print(f"退出，共 {len(samples)} 个样本。")


if __name__ == "__main__":
    main()
