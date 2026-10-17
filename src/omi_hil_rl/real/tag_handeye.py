"""Read-only tag10 eye-to-hand calibration: A_i Z = X B_i, metres.

A=base_link<-TCP, B=camera<-tag10, X=base_link<-camera, Z=TCP<-tag10.
"""
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import cv2
import numpy as np

from .tag_follow import transform

MIN_SAMPLES = 15


def mean_pose(poses):
    poses = [transform(t) for t in poses]
    u, _, vt = np.linalg.svd(sum(t[:3, :3] for t in poses))
    r = u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt
    t = np.eye(4)
    t[:3, :3], t[:3, 3] = r, np.mean([t[:3, 3] for t in poses], axis=0)
    return transform(t)


def distance(a, b):
    return (float(np.linalg.norm(a[:3, 3] - b[:3, 3]) * 1000),
            float(np.degrees(np.linalg.norm(cv2.Rodrigues(a[:3, :3].T @ b[:3, :3])[0]))))


def pose_message(msg, expected_frame='base_link'):
    if msg.header.frame_id != expected_frame:
        raise ValueError(f'TCP frame must be {expected_frame}, got {msg.header.frame_id}')
    p, q = msg.pose.position, msg.pose.orientation
    v = np.array([q.x, q.y, q.z, q.w], dtype=float)
    norm = np.linalg.norm(v)
    if not np.isfinite(v).all() or norm < 1e-8:
        raise ValueError('Invalid TCP quaternion')
    x, y, z, w = v / norm
    t = np.eye(4)
    t[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    t[:3, 3] = [p.x, p.y, p.z]
    return transform(t)


class PoseHistory:
    def __init__(self):
        self.values = deque(maxlen=1000)

    def add(self, stamp, matrix):
        if not np.isfinite(stamp) or stamp <= 0:
            raise ValueError('Invalid TCP timestamp')
        if self.values and stamp <= self.values[-1][0]:
            self.values.clear()
            raise ValueError('TCP clock repeated/backwards; capture again')
        self.values.append((stamp, transform(matrix)))

    def match(self, stamp, max_skew=.05):
        if not self.values:
            raise ValueError('Waiting for TCP feedback')
        value = min(self.values, key=lambda item: abs(item[0] - stamp))
        if abs(value[0] - stamp) > max_skew:
            raise ValueError('Image/TCP timestamps differ by more than 50ms')
        return value


class StableCapture:
    def __init__(self, after_stamp):
        self.after = after_stamp
        self.rows = []

    def add(self, image_stamp, robot_stamp, a, b, current_a, now_stamp):
        """Frames after the key press only; >=10 pairs spanning >=0.7s."""
        if image_stamp < self.after:
            return None
        if not 0 <= now_stamp - image_stamp <= 1.5:
            raise ValueError('Camera delay exceeds 1.5s; cannot pair this capture')
        if abs(image_stamp - robot_stamp) > .05:
            raise ValueError('Image/TCP skew exceeds 50ms')
        if self.rows and image_stamp <= self.rows[-1][0]:
            raise ValueError('Repeated/backwards image timestamp')
        a, b = transform(a), transform(b)
        if any(v > limit for v, limit in zip(distance(a, current_a), (2., .5))):
            raise ValueError('Robot moved since image capture; stop and press S again')
        if self.rows:
            if any(v > limit for v, limit in zip(distance(a, self.rows[0][2]), (2., .5))):
                raise ValueError('Robot moving during capture; stop and press S again')
            if any(v > limit for v, limit in zip(distance(b, self.rows[0][3]), (4., 2.))):
                raise ValueError('Tag pose unstable; hold still and press S again')
        self.rows.append((image_stamp, robot_stamp, a, b))
        if len(self.rows) < 10 or image_stamp - self.rows[0][0] < .7:
            return None
        return dict(A=mean_pose([r[2] for r in self.rows]).tolist(),
                    B=mean_pose([r[3] for r in self.rows]).tolist(), frames=len(self.rows),
                    image_stamp_start=self.rows[0][0], image_stamp_end=image_stamp,
                    max_pair_skew_ms=max(abs(r[0]-r[1])*1000 for r in self.rows))


def append_sample(samples, sample):
    a = transform(sample['A'])
    transform(sample['B'])
    for i, old in enumerate(samples):
        mm, degrees = distance(a, transform(old['A']))
        if mm < 10 and degrees < 5:
            raise ValueError(f'Too similar to sample {i+1}; change pose before capture')
    samples.append(sample)


def coverage(samples, minimum=MIN_SAMPLES):
    if len(samples) < minimum:
        raise ValueError(f'Need at least {minimum} distinct poses; currently {len(samples)}')
    aa = [transform(s['A']) for s in samples]
    rotations = np.array([cv2.Rodrigues(a[:3, :3].T @ b[:3, :3])[0].ravel()
                          for i, a in enumerate(aa) for b in aa[i+1:]])
    singular = np.linalg.svd(rotations, compute_uv=False)
    span = float(np.degrees(np.max(np.linalg.norm(rotations, axis=1))))
    if span < 20 or singular[0] < 1e-8 or singular[1] / singular[0] < .15:
        raise ValueError('Insufficient rotation coverage: tilt about at least two axes, span >=20deg')
    design = np.vstack([np.hstack((np.eye(3), -a[:3, :3])) for a in aa])
    s = np.linalg.svd(design, compute_uv=False)
    if s[-1] / s[0] < .01:
        raise ValueError('Translation solve is ill-conditioned; add diverse rotations')
    return dict(rotation_span_deg=span, rotation_axis_ratio=float(singular[1]/singular[0]),
                translation_condition=float(s[0]/s[-1]))


def residuals(x, z, samples):
    return np.array([distance(transform(s['A']) @ z, x @ transform(s['B'])) for s in samples])


def _fit(samples):
    aa = [np.linalg.inv(transform(s['A'])) for s in samples]
    bb = [transform(s['B']) for s in samples]
    candidates = []
    for name, method in [('PARK', cv2.CALIB_HAND_EYE_PARK), ('TSAI', cv2.CALIB_HAND_EYE_TSAI),
                         ('HORAUD', cv2.CALIB_HAND_EYE_HORAUD), ('DANIILIDIS', cv2.CALIB_HAND_EYE_DANIILIDIS)]:
        try:
            r, t = cv2.calibrateHandEye([a[:3, :3] for a in aa], [a[:3, 3] for a in aa],
                                      [b[:3, :3] for b in bb], [b[:3, 3] for b in bb], method=method)
            x = np.eye(4)
            x[:3, :3], x[:3, 3] = r, t.ravel()
            x = transform(x)
            z = mean_pose([a @ x @ b for a, b in zip(aa, bb)])
            error = residuals(x, z, samples)
            candidates.append((float(np.mean(error[:, 0]) + 2*np.mean(error[:, 1])), name, x, z, error))
        except (cv2.error, ValueError, np.linalg.LinAlgError):
            continue
    if not candidates:
        raise ValueError('No finite hand-eye solution')
    return min(candidates, key=lambda c: c[0])


def solve(samples):
    geometry = coverage(samples)
    _, method, x, z, errors = _fit(samples)
    validation = []
    for fold in range(3):
        train = [s for i, s in enumerate(samples) if i % 3 != fold]
        held = [s for i, s in enumerate(samples) if i % 3 == fold]
        coverage(train, minimum=10)
        _, _, xx, zz, _ = _fit(train)
        validation.extend(residuals(xx, zz, held))
    validation_rms = np.sqrt(np.mean(np.square(validation), axis=0))
    metrics = dict(residual_trans_mm_mean=float(np.mean(errors[:, 0])),
                   residual_rot_deg_mean=float(np.mean(errors[:, 1])),
                   residual_trans_mm_max=float(np.max(errors[:, 0])),
                   residual_rot_deg_max=float(np.max(errors[:, 1])),
                   validation_trans_mm_rms=float(validation_rms[0]),
                   validation_rot_deg_rms=float(validation_rms[1]))
    limits = dict(residual_trans_mm_mean=3.5, residual_rot_deg_mean=1.,
                  residual_trans_mm_max=10., residual_rot_deg_max=3.,
                  validation_trans_mm_rms=5., validation_rot_deg_rms=2.)
    if any(metrics[k] > limit for k, limit in limits.items()):
        worst = int(np.argmax(errors[:, 0] + 2*errors[:, 1])) + 1
        raise ValueError(f'Calibration quality rejected; worst sample={worst}; '+json.dumps(metrics))
    return dict(schema='omi-tag10-handeye-v1', X=x.tolist(), Z=z.tolist(),
                X_frame='base_link_from_camera', Z_frame='TCP_from_tag10', translation_unit='m',
                tag_id=10, tag_size_m=.051, n_samples=len(samples), method=method,
                created_utc=datetime.now(timezone.utc).isoformat(),
                quality_limits=limits, coverage=geometry,
                per_sample_residual_mm_deg=errors.tolist(), **metrics)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
