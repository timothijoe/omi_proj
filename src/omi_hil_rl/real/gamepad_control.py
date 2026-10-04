"""Gamepad mapping and single-owner action selection; internal units m/rad."""
from dataclasses import dataclass
import math
import numpy as np

# Linux input codes (not device-dependent joystick axis/button indices).
ABS_X, ABS_Y, ABS_RX, ABS_RY, ABS_HAT0X, ABS_HAT0Y = 0, 1, 3, 4, 16, 17
BTN_TR = 311


@dataclass
class Mapping:
    hz: float = 10.
    translation_m_s: float = .01
    rotation_rad_s: float = math.radians(10)
    deadzone: float = .15
    signs: tuple = (1, 1, 1, 1, 1, 1)

    def __post_init__(self):
        values = (self.hz, self.translation_m_s, self.rotation_rad_s)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError('Rate and speeds must be finite and positive')
        if not 0 <= self.deadzone < 1:
            raise ValueError('Deadzone must be in [0, 1)')
        if len(self.signs) != 6 or any(v not in (-1, 1) for v in self.signs):
            raise ValueError('Six signs, each -1 or 1, required')

    def action(self, axes):
        def stick(code):
            v = float(axes.get(code, 0.))
            if not math.isfinite(v):
                raise ValueError('Nonfinite joystick axis')
            v = max(-1., min(1., v))
            return math.copysign(max(0., abs(v)-self.deadzone)/(1-self.deadzone), v)
        def hat(code):
            v = float(axes.get(code, 0.))
            if not math.isfinite(v):
                raise ValueError('Nonfinite D-pad axis')
            return 0. if abs(v) < .5 else math.copysign(1., v)
        # +X forward, +Y left, +Z up; rotation signs configurable after bench check.
        d = np.array([-stick(ABS_RY), -stick(ABS_RX), -hat(ABS_HAT0Y),
                      stick(ABS_X), -stick(ABS_Y), -hat(ABS_HAT0X)])
        d *= self.signs
        for part, speed in ((d[:3], self.translation_m_s), (d[3:], self.rotation_rad_s)):
            part *= speed / self.hz / max(1., np.linalg.norm(part))
        return d


def wire_action(action, convention='legacy'):
    """Convert the selected policy-frame action immediately before publication."""
    from .sdk_action import output_action
    return output_action(action, convention)


class Arbiter:
    def __init__(self, mapping, timeout=.2):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid policy timeout')
        self.mapping, self.timeout = mapping, timeout
        self.policy = None
        self.barrier = float('-inf')
        self.last_stamp = float('-inf')
        self.held = False
        self.connected = False

    def offer(self, action, stamp, now):
        d = np.asarray(action, dtype=float)
        valid = (d.shape == (6,) and np.isfinite(d).all()
                 and math.isfinite(stamp) and 0 <= now-stamp <= self.timeout
                 and stamp > max(self.barrier, self.last_stamp)
                 and np.linalg.norm(d[:3]) <= self.mapping.translation_m_s/self.mapping.hz + 1e-12
                 and np.linalg.norm(d[3:]) <= self.mapping.rotation_rad_s/self.mapping.hz + 1e-12)
        if not valid:
            self.policy = None
            return False
        self.last_stamp = stamp
        self.policy = (stamp, d.copy())
        return True

    def select(self, connected, held, axes, now):
        if not connected or connected != self.connected or held != self.held:
            self.barrier = now
            self.policy = None
        self.connected, self.held = connected, held
        if not connected:
            return 'paused_disconnected', np.zeros(6)
        if held:
            self.policy = None
            return 'human', self.mapping.action(axes)
        candidate, self.policy = self.policy, None  # never replay a delta twice
        if candidate is not None and candidate[0] > self.barrier and 0 <= now-candidate[0] <= self.timeout:
            return 'policy', candidate[1]
        return 'paused_no_policy', np.zeros(6)
