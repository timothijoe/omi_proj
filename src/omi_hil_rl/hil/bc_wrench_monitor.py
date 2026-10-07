"""Per-episode, read-only BC wrench warnings in uncalibrated SDK units."""
from collections import deque
import math
from statistics import median


class BCWrenchMonitor:
    def __init__(self, *, force_xy_limit=1.5, torque_limit=0.4, emit=None):
        if any(not math.isfinite(value) or value <= 0
               for value in (force_xy_limit, torque_limit)):
            raise ValueError('wrench warning limits must be finite and positive')
        self.force_xy_limit = force_xy_limit
        self.torque_limit = torque_limit
        self.emit = emit or (lambda event: None)
        self.recent = {side: deque(maxlen=64) for side in ('a', 'b')}
        self.active = None
        self.last_warning = {}

    def ingest(self, side, values, now):
        values = tuple(float(value) for value in values)
        if side not in self.recent or len(values) != 6:
            raise ValueError('expected six wrench values for finger a or b')
        if not all(math.isfinite(value) for value in values):
            self.recent[side].clear()
            if self.active is not None:
                self.active['invalid_samples'][side] += 1
            return
        self.recent[side].append((now, values))
        episode = self.active
        if episode is None or now < episode['started_monotonic']:
            return
        if not any(values):
            episode['invalid_samples'][side] += 1
            return
        base = episode['baseline'][side]
        force_xy = math.hypot(values[0] - base[0], values[1] - base[1])
        torque = math.dist(values[3:], base[3:])
        episode['samples'][side] += 1
        episode['peaks'][side]['force_xy'] = max(episode['peaks'][side]['force_xy'], force_xy)
        episode['peaks'][side]['torque'] = max(episode['peaks'][side]['torque'], torque)
        if force_xy < self.force_xy_limit and torque < self.torque_limit:
            return
        episode['exceeded_samples'][side] += 1
        event = dict(side=side, elapsed_s=now - episode['started_monotonic'],
                     force_xy=force_xy, torque=torque, values=values)
        episode['first_exceedance'] = episode['first_exceedance'] or event
        if now - self.last_warning.get(side, float('-inf')) >= 1.0:
            self.last_warning[side] = now
            self.emit(event)

    def begin(self, episode_id, started):
        self.active = None
        self.last_warning.clear()
        baseline = {}
        for side in ('a', 'b'):
            window = [(when, values) for when, values in self.recent[side]
                      if started - 1.0 <= when <= started]
            if (len(window) < 20 or started - window[-1][0] > 0.2 or
                    window[-1][0] - window[0][0] < 0.4):
                return dict(episode=episode_id, status='baseline_unavailable',
                            reason=f'{side}: need 20 fresh samples spanning 0.4s before Start')
            if all(all(value == 0 for value in values) for _, values in window):
                return dict(episode=episode_id, status='baseline_unavailable',
                            reason=f'{side}: all-zero wrench stream before Start')
            center = tuple(median(row[i] for _, row in window) for i in range(6))
            force_spread = max(math.dist(row[:3], center[:3]) for _, row in window)
            torque_spread = max(math.dist(row[3:], center[3:]) for _, row in window)
            if force_spread > 0.5 or torque_spread > 0.15:
                return dict(episode=episode_id, status='baseline_unavailable',
                            reason=f'{side}: unstable before Start',
                            force_spread=force_spread, torque_spread=torque_spread)
            baseline[side] = center
        self.active = dict(episode=episode_id, status='monitoring',
                           started_monotonic=started, baseline=baseline,
                           force_xy_limit=self.force_xy_limit, torque_limit=self.torque_limit,
                           samples={'a': 0, 'b': 0}, exceeded_samples={'a': 0, 'b': 0},
                           invalid_samples={'a': 0, 'b': 0},
                           peaks={side: dict(force_xy=0., torque=0.) for side in ('a', 'b')},
                           first_exceedance=None, action_effect='none', label_effect='none')
        return dict(episode=episode_id, status='monitoring', baseline=baseline,
                    force_xy_limit=self.force_xy_limit, torque_limit=self.torque_limit)

    def finish(self, episode_id):
        episode, self.active = self.active, None
        if episode is None or episode['episode'] != episode_id:
            return None
        return episode
