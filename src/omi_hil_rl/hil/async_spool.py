"""Bounded snapshot queue; only the writer thread compresses/fsyncs episodes."""
from concurrent.futures import Future, TimeoutError
from copy import deepcopy
import queue
import threading

from .environment import InteractionUnavailable
from .exchange import EpisodeSpool


class RecordingError(InteractionUnavailable):
    pass


class AsyncEpisodeSpool:
    def __init__(self, run, episode, contract, *, origin='online', policy_version=0, capacity=32):
        if capacity < 1:
            raise ValueError('positive writer queue capacity required')
        self.count = 0
        self.error = None
        self.storage_failed = False
        self.prefix_success = None
        self.closed = False
        self.tasks = queue.Queue(maxsize=capacity)
        self.result = Future()
        self.args = (run, episode, deepcopy(contract))
        self.kwargs = dict(origin=origin, policy_version=policy_version)
        self.thread = threading.Thread(target=self._write, name='rl-episode-writer', daemon=True)
        self.thread.start()

    def check(self):
        if self.error is not None:
            raise RecordingError('episode writer failed: ' + self.error)

    def append(self, *args):
        if self.closed:
            raise RecordingError('episode writer already closing')
        self.check()
        # Ownership must not leak: callers reuse/modify observations and metadata.
        snapshot = deepcopy(args)
        try:
            self.tasks.put_nowait(('append', snapshot))
        except queue.Full:
            self.error = 'writer queue full; episode excluded, no silent sample dropping'
            raise RecordingError(self.error)
        self.count += 1

    def finish_valid_prefix(self, *, success):
        self.prefix_success = bool(success)

    def truncate_valid_prefix(self):
        self.finish_valid_prefix(success=False)

    def finish(self, keep, *, reason=None, tick=None):
        """Called only after stopping; service manual reset while writer drains."""
        if not self.closed:
            while True:
                try:
                    self.tasks.put(('finish', (keep, reason)), timeout=.01)
                    self.closed = True
                    break
                except queue.Full:
                    if tick:
                        tick()
        while True:
            try:
                value = self.result.result(timeout=.01)
                self.thread.join()
                return value
            except TimeoutError:
                if tick:
                    tick()

    def _write(self):
        spool = None
        try:
            spool = EpisodeSpool(*self.args, **self.kwargs)
        except Exception as exc:
            self.error = repr(exc)
            self.storage_failed = True
        while True:
            kind, payload = self.tasks.get()
            try:
                if kind == 'append':
                    if not self.storage_failed:
                        try:
                            spool.append(*payload)
                        except Exception as exc:
                            self.error = repr(exc)
                            self.storage_failed = True
                else:
                    keep, reason = payload
                    if spool is None:
                        raise RecordingError('cannot create episode: ' + str(self.error))
                    if self.error is None and self.prefix_success is not None:
                        spool.finish_valid_prefix(success=self.prefix_success)
                    value = spool.finish(keep and self.error is None,
                                         reason=self.error or reason)
                    self.result.set_result(value)
                    return
            except Exception as exc:
                self.error = repr(exc)
                self.result.set_exception(RecordingError(self.error))
                return
            finally:
                self.tasks.task_done()
