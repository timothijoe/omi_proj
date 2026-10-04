"""Convert policy-frame increments to SDK BASE mm / ABC-degree commands.

The installation preset is a hypothesis, not a measured calibration.
"""
import math
import numpy as np

OUTPUT_CONVENTIONS = ('legacy', 'sdk-base-aligned', 'sdk-x-forward-z-left')


def rotvec_to_sdk_abc(rotvec):
    """Return A,B,C degrees with Exp(rotvec) = Rz(C) Ry(B) Rx(A)."""
    r = np.asarray(rotvec, dtype=float)
    if r.shape != (3,) or not np.isfinite(r).all():
        raise ValueError('Expected finite rotation vector')
    angle = float(np.linalg.norm(r))
    if angle == 0:
        return np.zeros(3)
    x, y, z = r/angle
    K = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    R = np.eye(3) + math.sin(angle)*K + (1-math.cos(angle))*(K@K)
    cb = math.hypot(R[0, 0], R[1, 0])
    b = math.atan2(-R[2, 0], cb)
    if cb > 1e-10:
        a = math.atan2(R[2, 1], R[2, 2])
        c = math.atan2(R[1, 0], R[0, 0])
    else:
        # At +/-90 degree pitch the Euler representation is non-unique.
        a = math.atan2(-R[1, 2], R[1, 1])
        c = 0.
    return np.degrees([a, b, c])


def output_action(action, convention='legacy'):
    """Input: policy-frame dp(m), rotation vector(rad). Output: wire six-vector.

    legacy: same frame, mm / rotvec-degrees (historical sender).
    sdk-base-aligned: same frame, mm / ABC-degrees.
    sdk-x-forward-z-left: (x,y,z)->(x,-z,y), mm / ABC-degrees.
    SDK modes require FRAME_BASE and an aligned/identity UserFrame at receiver.
    """
    d = np.asarray(action, dtype=float)
    if d.shape != (6,) or not np.isfinite(d).all():
        raise ValueError('Expected six finite increments')
    if convention not in OUTPUT_CONVENTIONS:
        raise ValueError('Unknown output convention: '+str(convention))
    if convention == 'legacy':
        return np.r_[d[:3]*1000, np.degrees(d[3:])].tolist()
    p, r = d[:3], d[3:]
    if convention == 'sdk-x-forward-z-left':
        # Proper right-handed rotation: determinant +1. No origin translation
        # belongs in a displacement of the same TCP point.
        p = np.array([p[0], -p[2], p[1]])
        r = np.array([r[0], -r[2], r[1]])
    return np.r_[p*1000, rotvec_to_sdk_abc(r)].tolist()


def format_action_trace(mode, action, convention, output, published=False):
    """Show the selected source action and the exact command from one sample.

    Original is after deadzone/scale/signs/RB gating, before frame conversion.
    Both displays use mm/degree, with rotation representation stated explicitly.
    """
    original = output_action(action, 'legacy')
    enabled = convention != 'legacy'
    swap = convention == 'sdk-x-forward-z-left'
    def values(v):
        return '['+', '.join(f'{x:.6g}' if x != 0 else '0' for x in v)+']'
    return (f'状态={mode} | '+('已发布' if published else '仅预览')+
            f' | 原始(mm/deg旋转向量)={values(original)}'
            f' | 转换={"是" if enabled else "否"}({convention})'
            f' | 换轴={"是" if swap else "否"} | 转ABC={"是" if enabled else "否"}'
            f' | 转换后/最终(mm/deg{"ABC" if enabled else "旋转向量"})={values(output)}')
