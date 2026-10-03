"""Base-frame endpoint increments. Pure NumPy; no robot control or FK."""
from __future__ import annotations
import numpy as np

VERSION = "left-eef-base-delta-v1"

def quaternion(q):
    q = np.asarray(q, dtype=np.float64)
    if q.shape != (4,) or not np.isfinite(q).all():
        raise ValueError("Expected finite xyzw quaternion")
    norm = np.linalg.norm(q)
    if abs(norm-1.) > 1e-3:
        raise ValueError("Quaternion norm outside 1e-3 tolerance")
    q = q / norm
    # Unique sign, including exactly pi rotations; no dependence on past/future samples.
    pivot = 3 if abs(q[3]) > 1e-12 else int(np.argmax(np.abs(q[:3])))
    return -q if q[pivot] < 0 else q


def pose(value):
    value = np.asarray(value, dtype=np.float64)
    if value.shape != (7,) or not np.isfinite(value).all():
        raise ValueError("Expected finite xyz + xyzw pose")
    return np.r_[value[:3], quaternion(value[3:])]


def multiply(a, b):
    av, bv = a[:3], b[:3]
    return np.r_[a[3]*bv+b[3]*av+np.cross(av,bv), a[3]*b[3]-np.dot(av,bv)]


def rotvec(q):
    q = quaternion(q)
    n = np.linalg.norm(q[:3])
    return 2*q[:3] if n < 1e-12 else q[:3]*(2*np.arctan2(n,q[3])/n)


def from_rotvec(r):
    r = np.asarray(r, dtype=np.float64)
    if r.shape != (3,) or not np.isfinite(r).all():
        raise ValueError("Expected finite rotation vector")
    angle = np.linalg.norm(r)
    if angle > np.pi + 1e-10:
        raise ValueError("Rotation exceeds principal branch pi")
    scale = .5 if angle < 1e-12 else np.sin(angle/2)/angle
    return quaternion(np.r_[r*scale,np.cos(angle/2)])


def between(current, future):
    """[p_future-p_current, Log(R_future R_current^T)] in base axes."""
    a, b = pose(current), pose(future)
    inverse = np.r_[-a[3:6],a[6]]
    return np.r_[b[:3]-a[:3], rotvec(multiply(b[3:],inverse))]


def apply(current, action):
    """p_target=p_current+dp; R_target=Exp(dr) R_current (left multiply)."""
    a = pose(current)
    d = np.asarray(action,dtype=np.float64)
    if d.shape != (6,) or not np.isfinite(d).all():
        raise ValueError("Expected finite six-dimensional increment")
    return np.r_[a[:3]+d[:3],quaternion(multiply(from_rotvec(d[3:]),a[3:]))]


def check_increment(action, max_translation_m, max_rotation_rad):
    """Reject, never silently clip labels/predictions. Bounds are experimental."""
    d = np.asarray(action,dtype=np.float64)
    limits = np.asarray([max_translation_m,max_rotation_rad],dtype=np.float64)
    if not np.isfinite(limits).all() or np.any(limits <= 0) or max_rotation_rad > np.pi:
        raise ValueError("Invalid experimental increment bounds")
    if d.shape != (6,) or not np.isfinite(d).all():
        raise ValueError("Invalid action")
    if np.linalg.norm(d[:3]) > max_translation_m:
        raise ValueError("translation_bound")
    if np.linalg.norm(d[3:]) > max_rotation_rad:
        raise ValueError("rotation_bound")
    return d
