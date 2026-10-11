"""Bounded additive exploration in normalized action space, after arbitration."""
import math

import numpy as np


class GaussianExploration:
    def __init__(self, std=0., clip=.15, *, seed=None):
        if not math.isfinite(std) or not 0 <= std <= 1:
            raise ValueError('exploration noise std must be finite and in [0, 1]')
        if not math.isfinite(clip) or not 0 < clip <= 1:
            raise ValueError('exploration noise clip must be finite and in (0, 1]')
        self.std, self.clip = float(std), float(clip)
        # Independent of Learner/replay RNG; only consumed for selected policy commands.
        self.rng = np.random.default_rng(seed)

    def config(self):
        return dict(mode='clipped_gaussian' if self.std else 'off',
                    std=self.std, clip=self.clip, space='normalized_post_tanh',
                    policy_only=True)

    def apply(self, action):
        mean = np.asarray(action, dtype=np.float32)
        if mean.shape != (6,) or not np.isfinite(mean).all() or np.any(np.abs(mean) > 1):
            raise ValueError('exploration requires a finite normalized six-axis action')
        if not self.std:
            return mean.copy(), None
        noise = np.clip(self.rng.normal(0., self.std, 6), -self.clip, self.clip).astype(np.float32)
        selected = np.clip(mean + noise, -1., 1.).astype(np.float32)
        return selected, dict(self.config(), mean_action=mean.tolist(),
                              clipped_noise=noise.tolist(), applied_delta=(selected-mean).tolist())
