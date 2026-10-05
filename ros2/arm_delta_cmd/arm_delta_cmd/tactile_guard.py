"""Pure, SDK/ROS-free contact guard. Values are uncalibrated SDK units.

One fixed baseline per process, explicitly captured while holding the plug away
from the socket. A trip is latched; fresh data alone never clears it.
"""
from collections import deque
import math
from statistics import median


class TactileGuard:
    def __init__(self, *, enabled=False, force_limit=2.0, torque_limit=0.5,
                 timeout=0.2, retreat_step_mm=0.2, baseline_samples=20):
        for value in (force_limit, torque_limit, timeout, retreat_step_mm):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('guard limits/timeout must be finite and positive')
        if baseline_samples < 2:
            raise ValueError('baseline_samples must be >= 2')
        self.enabled = enabled
        self.force_limit, self.torque_limit = force_limit, torque_limit
        self.timeout, self.retreat_step_mm = timeout, retreat_step_mm
        self.samples = {s: deque(maxlen=baseline_samples) for s in ('a', 'b')}
        self.latest = {}
        self.baseline = None
        self.latched = False
        self.reason = 'unarmed'
        self.generation = 0

    def trip(self, reason):
        if not self.latched or self.reason != reason:
            self.generation += 1
        self.latched, self.reason = True, reason

    def update(self, side, values, now):
        if side not in self.samples:
            raise ValueError('unknown tactile side')
        values = tuple(float(v) for v in values)
        valid = len(values) == 6 and all(math.isfinite(v) for v in values)
        self.latest[side] = (now, values if valid else None)
        if valid:
            self.samples[side].append((now, values))
        else:
            self.samples[side].clear()
            self.trip('invalid_' + side)
        self.evaluate(now)

    def fault(self, now):
        for side in ('a', 'b'):
            if side not in self.latest:
                return 'missing_' + side
            when, values = self.latest[side]
            if values is None:
                return 'invalid_' + side
            if not 0 <= now - when <= self.timeout:
                return 'stale_' + side
        return None

    def metrics(self):
        if self.baseline is None:
            return {}
        result = {}
        for side, base in self.baseline.items():
            current = self.latest.get(side, (None, None))[1]
            if current is not None:
                delta = [v - b for v, b in zip(current, base)]
                result[side] = {'delta_force': math.hypot(*delta[:3]),
                                'delta_torque': math.hypot(*delta[3:])}
        return result

    def evaluate(self, now):
        if not self.enabled:
            return 'disabled'
        fault = self.fault(now)
        if fault:
            self.trip(fault)
            return fault
        if self.baseline is None:
            return 'unarmed'
        for side, metrics in self.metrics().items():
            if (metrics['delta_force'] >= self.force_limit or
                    metrics['delta_torque'] >= self.torque_limit):
                if not self.latched:
                    self.trip('overload_' + side)
        return 'latched' if self.latched else 'clear'

    def capture_baseline(self, now):
        if self.baseline is not None:
            return False, 'baseline already fixed; reset does not re-zero contact'
        if self.fault(now):
            return False, self.fault(now)
        baseline = {}
        for side, samples in self.samples.items():
            if len(samples) < samples.maxlen or now - samples[0][0] > 1.0:
                return False, 'need a recent full baseline window on both fingers'
            if any(b[0] - a[0] > self.timeout for a, b in zip(samples, list(samples)[1:])):
                return False, 'gap in baseline window'
            base = tuple(median(row[1][i] for row in samples) for i in range(6))
            for _, row in samples:
                if (math.hypot(*(row[i] - base[i] for i in range(3))) > self.force_limit / 4 or
                        math.hypot(*(row[i] - base[i] for i in range(3, 6))) > self.torque_limit / 4):
                    return False, 'baseline window is not stable'
            baseline[side] = base
        self.baseline = baseline
        self.latched, self.reason = False, 'clear'
        return True, 'fixed baseline captured; units/axes remain uncalibrated'

    def reset(self, now):
        self.evaluate(now)
        if self.fault(now) or self.baseline is None:
            return False, 'both sensors must be healthy and baseline must exist'
        if any(m['delta_force'] >= self.force_limit / 2 or
               m['delta_torque'] >= self.torque_limit / 2 for m in self.metrics().values()):
            return False, 'contact must fall below half of both trip limits'
        self.latched, self.reason = False, 'clear'
        return True, 'manually reset without changing baseline'

    def filter_action(self, action, now):
        action = tuple(float(v) for v in action)
        if len(action) != 6 or not all(math.isfinite(v) for v in action):
            return None, 'invalid_action'
        state = self.evaluate(now)
        if state in ('clear', 'disabled'):
            return action, state
        if state == 'latched' and action[0] < 0:
            return (max(action[0], -self.retreat_step_mm), 0., 0., 0., 0., 0.), 'retreat_only'
        return None, state

    def status(self, now):
        state = self.evaluate(now)
        return dict(enabled=self.enabled, state=state, reason=self.reason,
                    latched=self.latched, baseline=self.baseline, metrics=self.metrics(),
                    force_limit=self.force_limit, torque_limit=self.torque_limit,
                    timeout=self.timeout, retreat_step_mm=self.retreat_step_mm,
                    units='uncalibrated_sdk', freshness='host_receipt_only')
