"""SpacePilot velocity mapping and enable gate; no device/ROS side effects."""
from dataclasses import dataclass
import math

import numpy as np

from omi_hil_rl.hardware.spacepilot_pose import filtered, select_axes

DEFAULT_ENABLE_BUTTON = 19  # User-reported physical key 3 on current device setup.


@dataclass
class SpacePilotMapping:
    rate: float = 10.0
    speed_mm_s: float = 10.0
    rotation_deg_s: float = 10.0
    scale: float = 1.0
    translation_scale: float = 1.0
    rotation_scale: float = 1.0
    deadzone: float = 18.0
    mode: str = 'all'
    dominant: bool = False
    signs: tuple = (1, 1, 1, 1, 1, 1)

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.rate, self.speed_mm_s, self.rotation_deg_s)):
            raise ValueError('Rate and speeds must be finite and positive')
        if not all(math.isfinite(v) and v >= 0 for v in
                   (self.scale, self.translation_scale, self.rotation_scale)):
            raise ValueError('Scales must be finite and nonnegative')
        if not math.isfinite(self.deadzone) or not 0 <= self.deadzone < 350:
            raise ValueError('Deadzone must be in [0, 350)')
        if self.mode not in ('translation', 'rotation', 'all'):
            raise ValueError('Unknown motion mode')
        if len(self.signs) != 6 or any(v not in (-1, 1) for v in self.signs):
            raise ValueError('Six signs, each -1 or 1, required')
        if not all(math.isfinite(v) for v in (self.linear_speed, self.angular_speed)):
            raise ValueError('Scaled speed overflow')
        self.axis = None

    @property
    def linear_speed(self):
        return self.speed_mm_s * self.scale * self.translation_scale / 1000.0

    @property
    def angular_speed(self):
        return math.radians(self.rotation_deg_s) * self.scale * self.rotation_scale

    def reset(self):
        self.axis = None

    def action(self, raw):
        """raw is already map_motion output: X-forward/Y-left/Z-up, not pose."""
        raw = np.asarray(raw, dtype=float)
        if raw.shape != (6,) or not np.isfinite(raw).all():
            raise ValueError('Expected six finite SpacePilot axes')
        values = [filtered(v, self.deadzone) * sign for v, sign in zip(raw, self.signs)]
        # Disabled groups must not win dominant-axis selection.
        if self.linear_speed == 0:
            values[:3] = [0.] * 3
        if self.angular_speed == 0:
            values[3:] = [0.] * 3
        values, self.axis = select_axes(values, self.mode, self.dominant, self.axis)
        action = np.asarray(values)
        for part, speed in ((action[:3], self.linear_speed),
                            (action[3:], self.angular_speed)):
            part *= speed / self.rate / max(1., np.linalg.norm(part))
        return action


class EnableGate:
    """A fresh press is required after device reset or control-loop stall."""
    def __init__(self, button=DEFAULT_ENABLE_BUTTON, mode='hold'):
        if button < 0 or mode not in ('hold', 'toggle'):
            raise ValueError('Invalid enable button/mode')
        self.button, self.mode = button, mode
        self.reset()

    def reset(self):
        self.held = False
        self.enabled = False

    def on_button(self, number, pressed):
        if number != self.button:
            return
        if self.mode == 'hold':
            self.enabled = bool(pressed)
        elif pressed and not self.held:
            self.enabled = not self.enabled
        self.held = bool(pressed)


def selected_action(driver, gate, mapping, now):
    if not driver.connected or not driver.name:
        gate.reset()
        mode = 'disconnected'
    elif not gate.enabled:
        mode = 'idle'
    elif not 0 <= now - driver.last_motion <= .15:
        mode = 'stale'
    else:
        return 'human', mapping.action(driver.raw)
    mapping.reset()
    return mode, np.zeros(6)
