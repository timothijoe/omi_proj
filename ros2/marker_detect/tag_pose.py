#!/usr/bin/env python3
"""tag_pose.py — 稳健的 AprilTag 6-DoF 位姿估计 (单目 RGB, 可选 RealSense 对齐深度)

替代 pupil_apriltags 自带的 estimate_tag_pose, 输出坐标系与其完全一致
(角点顺序/tag 坐标轴相同), 所以已有的手眼标定 X、Z 可以直接沿用。

相对旧做法的改动, 按对抖动的影响从大到小:
  1. 平面位姿二义性 (IPPE 双解) 显式处理:
     小 tag / 近正视时两个解的重投影误差几乎一样, 旧方法每帧各挑各的, 表现为
     姿态在两个 "镜像" 解之间来回跳 (几度到几十度)。现在两个解都算出来,
     二义时按 深度平面法向 > 上一帧滤波结果 > 重投影误差 的优先级选。
  2. 角点亚像素精修: 沿 4 条边在原分辨率灰度图上做梯度峰值拟合 + 直线拟合,
     角点取相邻两边直线交点 (对模糊不敏感, 精度通常 0.05~0.1px)。
     检测器的 quad_decimate 只影响找四边形, 不再影响角点精度。
  3. 只检测一次 (旧代码按两种尺寸检测了两遍), 每个 id 用自己的物理尺寸解 PnP,
     并带上相机畸变参数。
  4. 时间滤波: 每个 tag 一个 SE(3) One-Euro 滤波 (静止时强平滑, 运动时低延迟),
     加跳变门限 (单帧异常跳变直接丢弃, 连续多帧才接受), 代替 4 帧滑动平均。
  5. (可选) 深度: tag 区域深度点拟合平面, 用于消歧, 也可以按权重融合法向和沿视线的距离。

用法:
    est = TagPoseEstimator(K, dist, tag_sizes={10: 0.051, 12: 0.064})
    obs = est.process(gray, stamp_s, depth_m=None)   # dict: id -> TagObs
    T_cam_tag = obs[12].T          # 滤波后 4x4, 相机系下 tag 位姿 (同 pupil 的 pose_R/pose_t)
    T_raw     = obs[12].T_raw      # 本帧单帧测量 (已消歧)
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

import cv2
import numpy as np
import pupil_apriltags as apriltag

# 与 pupil_apriltags 一致的 tag 系角点 (单位边长), 顺序与 det.corners 对应
OBJ_UNIT = np.array([[-0.5, 0.5, 0.0],
                     [0.5, 0.5, 0.0],
                     [0.5, -0.5, 0.0],
                     [-0.5, -0.5, 0.0]])


# ---------------------------------------------------------------- SO(3)/SE(3)
def so3_log(R):
    return cv2.Rodrigues(np.asarray(R, dtype=np.float64))[0].ravel()


def so3_exp(w):
    return cv2.Rodrigues(np.asarray(w, dtype=np.float64).reshape(3, 1))[0]


def rot_angle_deg(R):
    c = (np.trace(R) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def make_T(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.ravel(t)
    return T


# ---------------------------------------------------------------- 角点精修
def refine_corners_edges(gray, corners, max_shift_px=2.0, smooth_sigma=0.7):
    """沿四条边做亚像素边缘定位 + 加权直线拟合, 角点 = 相邻边直线交点。

    gray: uint8 原分辨率灰度图; corners: 4x2 (pupil 顺序)。
    返回 (corners_refined 4x2, ok_mask[4])。精修失败的角点保留原值。
    """
    c = np.asarray(corners, dtype=np.float64)
    side = np.mean([np.linalg.norm(c[(i + 1) % 4] - c[i]) for i in range(4)])
    if side < 12:
        return c.copy(), np.zeros(4, bool)
    cell = side / 8.0                      # tag36h11: 黑框外沿 = 8 个 cell
    r = float(np.clip(0.45 * cell, 2.0, 5.0))  # 搜索半宽 < 半个 cell, 避免跳到内边
    step = 0.25
    offs = np.arange(-r, r + 1e-9, step)
    mids = 0.5 * (offs[:-1] + offs[1:])

    # 只取 tag 周围 ROI 转 float, 做轻微高斯平滑 (对称核不引入直边偏移)
    pad = int(np.ceil(r + 4))
    x0, y0 = np.floor(c.min(0)).astype(int) - pad
    x1, y1 = np.ceil(c.max(0)).astype(int) + pad
    h, w = gray.shape[:2]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, w - 1), min(y1, h - 1)
    roi = gray[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    if smooth_sigma > 0:
        roi = cv2.GaussianBlur(roi, (0, 0), smooth_sigma)
    origin = np.array([x0, y0], dtype=np.float64)

    lines = []
    for i in range(4):
        a, b = c[i], c[(i + 1) % 4]
        d = b - a
        L = np.linalg.norm(d)
        d = d / L
        n = np.array([-d[1], d[0]])
        ns = int(np.clip(L / 1.5, 8, 120))
        fr = np.linspace(0.12, 0.88, ns)          # 避开角点附近
        P = a + fr[:, None] * (b - a)
        S = P[:, None, :] + offs[None, :, None] * n - origin
        # 双三次插值: 双线性插值的剖面是分段线性, 梯度峰值会被量化到像素格点
        vals = cv2.remap(roi, S[..., 0].astype(np.float32), S[..., 1].astype(np.float32),
                         cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        g = np.abs(np.diff(vals.astype(np.float64), axis=1))
        k = np.argmax(g, axis=1)
        M = g.shape[1]
        hw = int(round(1.25 / step))                  # 峰值两侧 ±1.25px 取梯度质心
        valid = (k >= hw) & (k < M - hw)
        idx = np.arange(ns)
        win = np.clip(k[:, None] + np.arange(-hw, hw + 1)[None, :], 0, M - 1)
        gw = g[idx[:, None], win]
        gmax = g[idx, k]
        wgt = np.maximum(gw - 0.25 * gmax[:, None], 0.0)
        pos = (wgt * mids[win]).sum(1) / np.maximum(wgt.sum(1), 1e-9)
        contrast = gmax
        valid &= contrast > 0.3 * np.median(contrast)
        pts = P + pos[:, None] * n
        wts = contrast
        line = _fit_line_robust(pts[valid], wts[valid])
        lines.append(line)

    out = c.copy()
    ok = np.zeros(4, bool)
    for i in range(4):
        la, lb = lines[(i - 1) % 4], lines[i]     # 角点 i 在边 i-1 与边 i 之间
        if la is None or lb is None:
            continue
        A = np.array([la[0], lb[0]])
        if abs(np.linalg.det(A)) < 1e-3:
            continue
        p = np.linalg.solve(A, np.array([la[1], lb[1]]))
        if np.linalg.norm(p - c[i]) <= max_shift_px:
            out[i] = p
            ok[i] = True
    return out, ok


def _fit_line_robust(pts, w, iters=2):
    """加权总体最小二乘直线 n·x = c, 两轮剔除离群点。"""
    if len(pts) < 5:
        return None
    m = np.ones(len(pts), bool)
    for _ in range(iters + 1):
        p, ww = pts[m], w[m]
        if len(p) < 5:
            return None
        mu = (p * ww[:, None]).sum(0) / ww.sum()
        q = (p - mu) * np.sqrt(ww)[:, None]
        _, _, Vt = np.linalg.svd(q, full_matrices=False)
        nrm = Vt[1]
        cc = nrm @ mu
        res = np.abs(pts @ nrm - cc)
        mad = np.median(res[m]) + 1e-6
        m = res < max(3.0 * 1.4826 * mad, 0.15)
    return nrm, cc


# ---------------------------------------------------------------- PnP
def solve_square_candidates(corners_px, size_m, K, dist):
    """IPPE_SQUARE 返回两个候选解, 各自 LM 精修。返回按重投影 RMS 升序的 [(R, t, rms)]。"""
    obj = OBJ_UNIT * size_m
    img = np.ascontiguousarray(corners_px, dtype=np.float64).reshape(-1, 1, 2)
    try:
        n, rvecs, tvecs, _ = cv2.solvePnPGeneric(obj, img, K, dist,
                                                 flags=cv2.SOLVEPNP_IPPE_SQUARE)
    except cv2.error:
        return []
    cands = []
    for rv, tv in zip(rvecs, tvecs):
        rv, tv = cv2.solvePnPRefineLM(obj, img, K, dist, rv.copy(), tv.copy())
        proj, _ = cv2.projectPoints(obj, rv, tv, K, dist)
        rms = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img.reshape(-1, 2)) ** 2, 1))))
        R = cv2.Rodrigues(rv)[0]
        if tv.ravel()[2] > 0:
            cands.append((R, tv.ravel().copy(), rms))
    cands.sort(key=lambda x: x[2])
    return cands


# ---------------------------------------------------------------- 深度平面
def fit_depth_plane(depth_m, K, corners_px, shrink=0.8, max_pts=2000, min_pts=60):
    """在 tag 四边形内 (向中心收缩) 取对齐深度, 鲁棒拟合平面。

    depth_m: HxW float32 米 (已对齐到彩色图, 0 = 无效)。
    返回 dict(n=法向(指向相机), p0=质心, rms=残差m, n_pts) 或 None。
    """
    c = np.asarray(corners_px, dtype=np.float64)
    ctr = c.mean(0)
    poly = (ctr + shrink * (c - ctr)).astype(np.int32)
    x0, y0 = poly.min(0)
    x1, y1 = poly.max(0) + 1
    h, w = depth_m.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillConvexPoly(mask, poly - [x0, y0], 1)
    sub = depth_m[y0:y1, x0:x1]
    vv, uu = np.nonzero((mask > 0) & (sub > 0.05))
    if len(vv) < min_pts:
        return None
    if len(vv) > max_pts:
        sel = np.random.default_rng(0).choice(len(vv), max_pts, replace=False)
        vv, uu = vv[sel], uu[sel]
    z = sub[vv, uu].astype(np.float64)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    X = np.column_stack([(uu + x0 - cx) / fx * z, (vv + y0 - cy) / fy * z, z])
    m = np.ones(len(X), bool)
    for _ in range(3):
        mu = X[m].mean(0)
        _, _, Vt = np.linalg.svd(X[m] - mu, full_matrices=False)
        nrm = Vt[2]
        res = np.abs((X - mu) @ nrm)
        mad = np.median(res[m]) + 1e-6
        m = res < max(3.0 * 1.4826 * mad, 0.002)
        if m.sum() < min_pts:
            return None
    if nrm @ mu > 0:          # 法向朝向相机
        nrm = -nrm
    return dict(n=nrm, p0=mu, rms=float(np.sqrt(np.mean(res[m] ** 2))), n_pts=int(m.sum()))


# ---------------------------------------------------------------- 滤波
class OneEuroSE3:
    """SE(3) 上的 One-Euro 滤波: 截止频率随速度自适应。
    静止 -> min_cutoff (强平滑); 运动 -> min_cutoff + beta*速度 (低延迟)。
    平移速度单位 m/s, 角速度 rad/s。"""

    def __init__(self, min_cutoff_t=1.0, beta_t=50.0, min_cutoff_r=1.0, beta_r=5.0, d_cutoff=1.0):
        self.mct, self.bt = min_cutoff_t, beta_t
        self.mcr, self.br = min_cutoff_r, beta_r
        self.dc = d_cutoff
        self.reset()

    def reset(self):
        self.T = None
        self.stamp = None
        self.vt = 0.0       # 平滑后的平移速度标量
        self.vr = 0.0       # 平滑后的角速度标量

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def update(self, T_meas, stamp):
        if self.T is None:
            self.T, self.stamp = T_meas.copy(), stamp
            return self.T
        dt = max(stamp - self.stamp, 1e-3)
        self.stamp = stamp
        R, t = self.T[:3, :3], self.T[:3, 3]
        dtr = T_meas[:3, 3] - t
        w = so3_log(R.T @ T_meas[:3, :3])          # 机体系误差
        ad = self._alpha(self.dc, dt)
        self.vt += ad * (np.linalg.norm(dtr) / dt - self.vt)
        self.vr += ad * (np.linalg.norm(w) / dt - self.vr)
        at = self._alpha(self.mct + self.bt * self.vt, dt)
        ar = self._alpha(self.mcr + self.br * self.vr, dt)
        self.T = make_T(R @ so3_exp(ar * w), t + at * dtr)
        return self.T


@dataclass
class FilterParams:
    min_cutoff_t: float = 1.0     # Hz
    beta_t: float = 40.0          # 每 (m/s) 增加的截止频率
    min_cutoff_r: float = 1.0
    beta_r: float = 4.0           # 每 (rad/s)
    d_cutoff: float = 1.0
    gate_t_m: float = 0.03        # 单帧跳变门限 (超过视为异常)
    gate_r_deg: float = 8.0
    accept_after: int = 4         # 连续多少帧异常后承认它 (重新初始化)
    reset_after_s: float = 0.5    # 丢失超过此时长, 下次重新初始化


# 静止参考 tag (桌面): 更强平滑; 运动 tag (腕部): 更低延迟
STATIC_TAG_FILTER = FilterParams(min_cutoff_t=0.3, beta_t=20.0, min_cutoff_r=0.3, beta_r=2.0)
MOVING_TAG_FILTER = FilterParams(min_cutoff_t=2.0, beta_t=150.0, min_cutoff_r=1.5, beta_r=15.0, d_cutoff=2.0)


class TagTrack:
    def __init__(self, fp: FilterParams):
        self.fp = fp
        self.f = OneEuroSE3(fp.min_cutoff_t, fp.beta_t, fp.min_cutoff_r, fp.beta_r, fp.d_cutoff)
        self.last_stamp = None
        self.n_reject = 0

    def prior(self, stamp):
        if self.f.T is None or self.last_stamp is None:
            return None
        if stamp - self.last_stamp > self.fp.reset_after_s:
            return None
        return self.f.T

    def update(self, T_meas, stamp, strong=False):
        """返回 (T_filtered, rejected)"""
        if self.prior(stamp) is None:
            self.f.reset()
            self.n_reject = 0
            self.last_stamp = stamp
            return self.f.update(T_meas, stamp), False
        self.last_stamp = stamp
        T = self.f.T
        dt_m = np.linalg.norm(T_meas[:3, 3] - T[:3, 3])
        dr = rot_angle_deg(T[:3, :3].T @ T_meas[:3, :3])
        if dt_m > self.fp.gate_t_m or dr > self.fp.gate_r_deg:
            self.n_reject += 1
            need = max(2, self.fp.accept_after // 2) if strong else self.fp.accept_after
            if self.n_reject >= need:
                self.f.reset()
                self.n_reject = 0
                return self.f.update(T_meas, stamp), False
            return T, True
        self.n_reject = 0
        return self.f.update(T_meas, stamp), False


# ---------------------------------------------------------------- 主类
@dataclass
class TagObs:
    tag_id: int
    T: np.ndarray                 # 滤波后 4x4 (相机系)
    T_raw: np.ndarray             # 单帧测量 (已消歧)
    corners: np.ndarray           # 精修后角点 4x2
    reproj_rms: float             # 选中解的重投影 RMS (px)
    ambiguity: float              # 次优解/最优解 重投影比, 越接近 1 越二义
    side_px: float                # tag 在图像中的边长 (px)
    decision_margin: float
    chose_alt: bool = False       # 是否因先验/深度选了重投影次优的解
    depth: Optional[dict] = None  # 深度平面拟合结果
    rejected: bool = False        # 本帧测量被跳变门限丢弃
    stamp: float = 0.0


class TagPoseEstimator:
    def __init__(self, K, dist, tag_sizes: Dict[int, float], family='tag36h11',
                 image_width=None, quad_decimate=None, nthreads=4,
                 refine=True, ambiguity_ratio=3.0, min_margin=25.0, max_hamming=1,
                 filter_params: Optional[Dict[int, FilterParams]] = None,
                 depth_mode='disambiguate', depth_w_normal=0.5, depth_w_range=0.3):
        """
        K: 3x3 内参; dist: 畸变系数 (RealSense coeffs, 可全 0)
        tag_sizes: {id: 黑框外沿边长 m}; 只输出这些 id
        quad_decimate: None 时按宽度自动: <=1280 用 1.0, 更大用 2.0 (角点精修在原图上做)
        ambiguity_ratio: 次优/最优重投影误差 < 此值视为二义, 启用先验/深度消歧
        depth_mode: 'off' | 'disambiguate' (只用深度选解) | 'fuse' (再按权重融合法向/距离)
        """
        self.K = np.asarray(K, dtype=np.float64)
        self.dist = np.zeros(5) if dist is None else np.asarray(dist, dtype=np.float64).ravel()
        self.sizes = dict(tag_sizes)
        if quad_decimate is None:
            quad_decimate = 1.0 if (image_width is None or image_width <= 1280) else 2.0
        self.detector = apriltag.Detector(families=family, nthreads=nthreads,
                                          quad_decimate=quad_decimate, quad_sigma=0.0,
                                          refine_edges=1, decode_sharpening=0.25)
        self.refine = refine
        self.corner_offset = 0.5
        self.amb_ratio = ambiguity_ratio
        self.min_margin = min_margin
        self.max_hamming = max_hamming
        self.depth_mode = depth_mode
        self.w_n, self.w_r = depth_w_normal, depth_w_range
        fps = filter_params or {}
        self.tracks = {i: TagTrack(fps.get(i, FilterParams())) for i in self.sizes}

    # -- 单个 tag 的单帧测量 --
    def _measure(self, gray, det, stamp, depth_m):
        tid = det.tag_id
        size = self.sizes[tid]
        # apriltag 库的角点坐标比 OpenCV/RealSense 内参约定 (像素中心为整数) 偏 +0.5px,
        # 合成图实测 4 个角点一致偏 (+0.5, +0.5), 不修正会引入系统误差
        corners = det.corners.astype(np.float64) - self.corner_offset
        if self.refine:
            corners, _ = refine_corners_edges(gray, corners)
        side = float(np.mean([np.linalg.norm(corners[(i + 1) % 4] - corners[i]) for i in range(4)]))
        cands = solve_square_candidates(corners, size, self.K, self.dist)
        if not cands:
            return None
        ratio = cands[1][2] / max(cands[0][2], 1e-3) if len(cands) > 1 else np.inf

        plane = None
        if depth_m is not None and self.depth_mode != 'off':
            plane = fit_depth_plane(depth_m, self.K, corners)

        choice = 0
        if len(cands) > 1 and ratio < self.amb_ratio:
            if plane is not None:
                # tag z 轴 (pupil 约定) 指向远离相机, 应与 -n_depth 一致
                ang = [np.degrees(np.arccos(np.clip(R[:, 2] @ -plane['n'], -1, 1)))
                       for R, _, _ in cands]
                choice = int(np.argmin(ang))
            else:
                pr = self.tracks[tid].prior(stamp)
                if pr is not None:
                    ang = [rot_angle_deg(pr[:3, :3].T @ R) for R, _, _ in cands]
                    choice = int(np.argmin(ang))
        R, t, rms = cands[choice]

        if plane is not None and self.depth_mode == 'fuse':
            R, t = self._fuse_depth(R, t, corners, plane)

        strong = ratio >= 2 * self.amb_ratio
        return dict(R=R, t=t, rms=rms, ratio=ratio, side=side, corners=corners,
                    chose_alt=choice != 0, plane=plane, strong=strong)

    def _fuse_depth(self, R, t, corners, plane):
        # 1) 法向: tag z 轴向 -n_depth 方向转过 w_n 比例 (只动 tilt, 不动面内转角)
        z = R[:, 2]
        zd = -plane['n']
        axis = np.cross(z, zd)
        s = np.linalg.norm(axis)
        if s > 1e-9:
            ang = np.arctan2(s, z @ zd)
            R = so3_exp(axis / s * ang * self.w_n) @ R
        # 2) 距离: tag 中心视线与深度平面求交, 只沿视线方向融合 (横向位置 PnP 更准)
        c = np.asarray(corners)
        ctr_px = _diag_intersection(c)
        ray = np.linalg.solve(self.K, np.array([ctr_px[0], ctr_px[1], 1.0]))
        ray /= np.linalg.norm(ray)
        den = plane['n'] @ ray
        if abs(den) > 1e-3:
            lam_d = (plane['n'] @ plane['p0']) / den
            lam_p = t @ ray
            if lam_d > 0 and abs(lam_d - lam_p) < 0.05:
                t = t + self.w_r * (lam_d - lam_p) * ray
        return R, t

    def process(self, gray, stamp, depth_m=None) -> Dict[int, TagObs]:
        """gray: uint8 灰度原图; stamp: 秒 (建议用相机帧时间戳);
        depth_m: 可选, 对齐到彩色的深度 (float32 米)。"""
        out = {}
        dets = self.detector.detect(gray)
        best = {}
        for d in dets:
            if d.tag_id not in self.sizes or d.hamming > self.max_hamming:
                continue
            if d.decision_margin < self.min_margin:
                continue
            if d.tag_id not in best or d.decision_margin > best[d.tag_id].decision_margin:
                best[d.tag_id] = d
        for tid, d in best.items():
            m = self._measure(gray, d, stamp, depth_m)
            if m is None:
                continue
            T_raw = make_T(m['R'], m['t'])
            T_f, rej = self.tracks[tid].update(T_raw, stamp, strong=m['strong'])
            out[tid] = TagObs(tag_id=tid, T=T_f.copy(), T_raw=T_raw, corners=m['corners'],
                              reproj_rms=m['rms'], ambiguity=m['ratio'], side_px=m['side'],
                              decision_margin=float(d.decision_margin), chose_alt=m['chose_alt'],
                              depth=m['plane'], rejected=rej, stamp=stamp)
        return out


def _diag_intersection(c):
    """四边形对角线交点 = tag 中心的投影 (射影不变)"""
    p1, p2, p3, p4 = [np.append(x, 1.0) for x in c]
    l1, l2 = np.cross(p1, p3), np.cross(p2, p4)
    x = np.cross(l1, l2)
    return x[:2] / x[2]


def realsense_K_dist(intr):
    """pyrealsense2 intrinsics -> (K, dist)"""
    K = np.array([[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1.0]])
    coeffs = np.array(list(intr.coeffs)[:5], dtype=np.float64)
    model = str(intr.model).lower()
    # OpenCV 的畸变模型 = Brown-Conrady (k1,k2,p1,p2,k3 顺序一致)。
    # D435 彩色常报 inverse_brown_conrady 且系数全 0; 若是 inverse 且非零, 不能直接给 OpenCV。
    if 'inverse' in model and np.any(np.abs(coeffs) > 1e-9):
        print(f'[tag_pose] 警告: 畸变模型 {model} 不是 OpenCV 模型, 忽略畸变系数 {coeffs}')
        coeffs = np.zeros(5)
    elif 'brown' not in model and np.any(np.abs(coeffs) > 1e-9):
        print(f'[tag_pose] 警告: 未知畸变模型 {model}, 忽略畸变系数')
        coeffs = np.zeros(5)
    return K, coeffs
