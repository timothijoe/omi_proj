"""AprilTag relative-pose target, button edges and bounded SDK commands.

Transforms T_a_b map points in b into a. Translations are metres internally.
No ROS, camera, gamepad device or robot is opened by this module.
"""
import json
import os
from pathlib import Path
import tempfile

import cv2
import numpy as np

from .sdk_action import rotvec_to_sdk_abc

BTN_LB, BTN_START, BTN_SAVE, BTN_RB = 310, 304, 305, 311
TAG_SIZES = {10: .051, 12: .064}
R_MOUNT = np.array([[1., 0, 0], [0, 0, 1.], [0, -1., 0]])

# Per-command increments at 10 Hz. Lower gain/steps accommodate delayed vision.
KP_TRANSLATION = .08
KP_ROTATION = .08
MAX_STEP_MM = .5
MAX_STEP_DEG = .2
TRANSLATION_DEADBAND_MM = 2.5
TRANSLATION_RESUME_MM = 3.5
ROTATION_DEADBAND_DEG = .8
ROTATION_RESUME_DEG = 1.2


def control_description():
    return (f'比例增益 平移={KP_TRANSLATION:g}/旋转={KP_ROTATION:g}; '
            f'每轴每周期最大 {MAX_STEP_MM:g}mm/{MAX_STEP_DEG:g}deg; '
            f'独立停止阈值 {TRANSLATION_DEADBAND_MM:g}mm/{ROTATION_DEADBAND_DEG:g}deg; '
            f'恢复阈值 {TRANSLATION_RESUME_MM:g}mm/{ROTATION_RESUME_DEG:g}deg')


def transform(value):
    t = np.asarray(value, dtype=float)
    if (t.shape != (4, 4) or not np.isfinite(t).all()
            or not np.allclose(t[3], [0, 0, 0, 1], atol=1e-8)
            or not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(t[:3, :3]), 1., atol=1e-5)):
        raise ValueError('Expected a finite rigid 4x4 transform (translation in metres)')
    return t.copy()


def load_calibration(path):
    data = json.loads(Path(path).read_text())
    return transform(data['X']), transform(data['Z'])


def load_default(path):
    data = json.loads(Path(path).read_text())
    if (data.get('version') != 1 or data.get('frame') != 'tag10_from_tag12'
            or data.get('translation_unit') != 'm'
            or data.get('tag_sizes_m') != {str(k): v for k, v in TAG_SIZES.items()}):
        raise ValueError('Default pose has incompatible frames, units or tag sizes')
    return transform(data['T_tag10_tag12'])


def save_default(path, relative):
    path = Path(path)
    data = dict(version=1, frame='tag10_from_tag12', translation_unit='m',
                tag_sizes_m={str(k): v for k, v in TAG_SIZES.items()},
                T_tag10_tag12=transform(relative).tolist())
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


class FollowButtons:
    """One action per A/B press; ignore connection/init holds and ambiguous chords."""
    def __init__(self):
        self.connected = False
        self.held = {}
        self.ready = False

    def select(self, connected, buttons, events=()):
        if not connected:
            self.connected, self.ready, self.held = False, False, {}
            return 'stop'
        if not self.connected:
            self.connected = True
            self.held = dict(buttons)
            self.ready = not (buttons.get(BTN_START) or buttons.get(BTN_SAVE))
            return None
        if buttons.get(BTN_RB):
            self.held = dict(buttons)
            self.ready = False
            return 'stop'
        if any(code == BTN_RB and pressed and not initial for code, pressed, initial in events):
            self.held = dict(buttons)
            self.ready = False
            return 'stop'
        # Event order captures even a quick press/release within one poll.
        if not events:
            events = [(k, bool(buttons.get(k)), False)
                      for k in (BTN_LB, BTN_START, BTN_SAVE)
                      if bool(buttons.get(k)) != bool(self.held.get(k))]
        actions = []
        pressed_codes = {code for code, pressed, initial in events
                         if pressed and not initial and code in (BTN_START, BTN_SAVE)}
        for code, pressed, initial in events:
            self.held[code] = pressed
            if code in (BTN_START, BTN_SAVE):
                other = BTN_SAVE if code == BTN_START else BTN_START
                if (pressed and not initial and self.ready and self.held.get(BTN_LB)
                        and not self.held.get(other) and not self.held.get(BTN_RB)):
                    actions.append('save' if code == BTN_SAVE else 'toggle')
                self.ready = not (self.held.get(BTN_START) or self.held.get(BTN_SAVE))
        self.held = dict(buttons)
        self.ready = not (buttons.get(BTN_START) or buttons.get(BTN_SAVE))
        if (len(actions) == 1 and len(pressed_codes) < 2
                and not (buttons.get(BTN_START) and buttons.get(BTN_SAVE))):
            return actions[0]
        return None


class FollowController:
    def __init__(self, calibration=None, default=None):
        self.calibration = calibration
        self.default = None if default is None else transform(default)
        self.active = False
        self.target = None
        self.pair = None
        self.received = float('-inf')
        self.reason = 'waiting for tags'
        self.error_mm_rotvec_deg = np.zeros(6)
        self.translation_holding = False
        self.rotation_holding = False

    def observe(self, observations, received):
        self.pair = None
        for tid in TAG_SIZES:
            o = observations.get(tid)
            if o is None or o.rejected or not np.isfinite(o.side_px) or o.side_px < 20:
                self.reason = f'tag{tid} missing/rejected/too small'
                return
        self.pair = tuple(transform(observations[tid].T) for tid in TAG_SIZES)
        self.received = received
        self.reason = ''

    def fresh(self, now):
        return self.pair is not None and 0 <= now - self.received < .12

    def capture(self, now):
        if not self.fresh(now):
            raise ValueError('Both tags must be visible and fresh to capture')
        b10, b12 = self.pair
        return transform(np.linalg.inv(b10) @ b12)

    def start(self, now, temporary=None):
        target = self.default if temporary is None else transform(temporary)
        if target is None:
            raise ValueError('Save a default with LB+305 first')
        if self.calibration is None:
            raise ValueError('Following requires X/Z hand-eye calibration')
        if not self.fresh(now):
            raise ValueError('Both tags must be visible and fresh to start')
        self.target = target.copy()
        self.translation_holding = self.rotation_holding = False
        self.active = True

    def stop(self):
        self.active = False
        self.translation_holding = self.rotation_holding = False

    def state(self, now):
        if not self.active:
            return 'STOPPED'
        if not self.fresh(now):
            return 'PAUSED'
        return 'HOLDING' if self.translation_holding and self.rotation_holding else 'TRACKING'

    def command(self, now):
        self.error_mm_rotvec_deg = np.zeros(6)
        if not self.active or not self.fresh(now):
            if self.active and self.pair is not None:
                self.reason = 'camera frame stale'
            return np.zeros(6)
        b10, b12 = self.pair
        x, z = self.calibration
        # D = inv(B10_saved) B12_saved. Restore B10_des = B12_now inv(D).
        current = x @ b10 @ np.linalg.inv(z)
        desired = x @ b12 @ np.linalg.inv(self.target) @ np.linalg.inv(z)
        p = R_MOUNT.T @ (desired[:3, 3] - current[:3, 3]) * 1000
        rotation = R_MOUNT.T @ (desired[:3, :3] @ current[:3, :3].T) @ R_MOUNT
        w = cv2.Rodrigues(rotation)[0].ravel()
        w_deg = np.degrees(w)
        self.error_mm_rotvec_deg = np.r_[p, w_deg]
        # Each channel stops independently. Once stopped, a wider resume band
        # prevents small measurement changes at the boundary from restarting it.
        p_limit = TRANSLATION_RESUME_MM if self.translation_holding else TRANSLATION_DEADBAND_MM
        r_limit = ROTATION_RESUME_DEG if self.rotation_holding else ROTATION_DEADBAND_DEG
        self.translation_holding = np.linalg.norm(p) <= p_limit
        self.rotation_holding = np.linalg.norm(w_deg) <= r_limit
        dp = (np.zeros(3) if self.translation_holding else
              np.clip(KP_TRANSLATION * p, -MAX_STEP_MM, MAX_STEP_MM))
        dw = (np.zeros(3) if self.rotation_holding else
              np.radians(np.clip(KP_ROTATION * w_deg, -MAX_STEP_DEG, MAX_STEP_DEG)))
        abc = rotvec_to_sdk_abc(dw)
        # ABC decomposition can exceed the component bound slightly.
        return np.r_[dp, np.clip(abc, -MAX_STEP_DEG, MAX_STEP_DEG)]

    def action(self, now):
        """SDK-base m/rotvec radians for the shared transport's ABC conversion."""
        wire = self.command(now)
        a, b, c = np.radians(wire[3:])
        rx = cv2.Rodrigues(np.array([a, 0., 0.]))[0]
        ry = cv2.Rodrigues(np.array([0., b, 0.]))[0]
        rz = cv2.Rodrigues(np.array([0., 0., c]))[0]
        return np.r_[wire[:3] / 1000., cv2.Rodrigues(rz @ ry @ rx)[0].ravel()]


class FollowButtonFilter:
    """Reserve LB+A/B through release, including quick event-only chords."""
    def __init__(self):
        self.lb = False
        self.claimed = set()

    def gripper_input(self, buttons, events):
        filtered = []
        for code, pressed, initial in events:
            if code == BTN_LB:
                self.lb = bool(pressed)
            if code in (BTN_START, BTN_SAVE):
                if pressed and self.lb:
                    self.claimed.add(code)
                if code in self.claimed:
                    continue
            filtered.append((code, pressed, initial))
        self.lb = bool(buttons.get(BTN_LB))
        if self.lb:
            self.claimed.update(code for code in (BTN_START, BTN_SAVE) if buttons.get(code))
        masked = {code: held for code, held in buttons.items() if code not in self.claimed}
        filtered = [event for event in filtered if event[0] not in self.claimed]
        self.claimed.intersection_update(code for code in self.claimed if buttons.get(code))
        return masked, filtered
