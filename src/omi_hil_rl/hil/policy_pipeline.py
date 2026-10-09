"""One inference worker, one replaceable input, one candidate; no ROS or output."""
import threading
import time

import numpy as np


class LatestPolicy:
    def __init__(self, infer, *, consume_results=False):
        self.infer = infer
        self.cv = threading.Condition()
        self.generation = 0
        self.pending = self.result = self.error = self.last_key = None
        self.closed = False
        self.consume_results = consume_results
        self.result_observation = None
        self.thread = threading.Thread(target=self._work, name='rl-policy-inference', daemon=True)
        self.thread.start()

    def invalidate(self):
        with self.cv:
            self.generation += 1
            self.pending = self.result = self.last_key = None
            self.result_observation = None
            self.cv.notify_all()

    def offer(self, observation, stamp):
        # Windows are immutable after publication by StackObservations. Copying
        # here also makes worker ownership explicit for alternate transports.
        with self.cv:
            self.check()
            key = (self.generation, stamp)
            if self.closed or key == self.last_key:
                return
            self.last_key = key
            self.pending = (key, {k: v.copy() for k, v in observation.items()})
            self.cv.notify()

    def check(self):
        if self.error is not None:
            raise RuntimeError('background policy inference failed: ' + self.error)

    def get(self, stamp):
        with self.cv:
            self.check()
            if self.result is not None and self.result[0] == (self.generation, stamp):
                return self.result[1].copy(), self.result[2]
            return None

    def take(self):
        """Deliver every completed result once, including its actual input snapshot.

        A completed result is never replaced by a faster subsequent inference.
        Pending inputs still collapse to the latest while inference is busy.
        """
        with self.cv:
            self.check()
            if self.result is None:
                return None
            key, action, elapsed = self.result
            observation = self.result_observation
            self.result = self.result_observation = None
            self.cv.notify_all()
            return observation, key[1], action.copy(), elapsed

    def _work(self):
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.closed or (self.pending is not None and
                                 (not self.consume_results or self.result is None)))
                if self.closed:
                    return
                key, observation = self.pending
                self.pending = None
            try:
                start = time.monotonic_ns()
                action = np.asarray(self.infer(observation), dtype=np.float32)
                if action.shape != (6,) or not np.isfinite(action).all() or (np.abs(action) > 1).any():
                    raise ValueError('invalid normalized policy action')
                elapsed = (time.monotonic_ns()-start)/1e6
                with self.cv:
                    if not self.closed and key[0] == self.generation:
                        self.result = (key, action.copy(), elapsed)
                        self.result_observation = observation
            except Exception as exc:
                with self.cv:
                    self.error = repr(exc)
                return

    def close(self):
        with self.cv:
            self.closed = True
            self.generation += 1
            self.pending = self.result = None
            self.cv.notify()
        self.thread.join()  # No ROS/GPU state is destroyed while inference uses it.
