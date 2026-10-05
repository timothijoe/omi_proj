"""Bounded complete-JPEG queue; overload is counted, never hidden."""
from collections import Counter, deque
import threading


class FrameQueue:
    def __init__(self, mode='record', max_frames=60, max_bytes=64*1024**2):
        if mode not in ('latest', 'record') or max_frames < 1 or max_bytes < 1:
            raise ValueError('invalid frame queue configuration')
        self.mode, self.max_frames, self.max_bytes = mode, max_frames, max_bytes
        self.frames, self.bytes = deque(), 0
        self.counters, self.lock = Counter(), threading.Lock()

    def put(self, frame):
        size = len(frame[2])
        with self.lock:
            self.counters['received_complete'] += 1
            if size > self.max_bytes:
                self.counters['oversize_drops'] += 1
                return
            limit = 1 if self.mode == 'latest' else self.max_frames
            while self.frames and (len(self.frames) >= limit or self.bytes+size > self.max_bytes):
                self.bytes -= len(self.frames.popleft()[2])
                self.counters['latest_overwrites' if self.mode == 'latest' else 'queue_overflow_drops'] += 1
            self.frames.append(frame)
            self.bytes += size
            self.counters['peak_frames'] = max(self.counters['peak_frames'], len(self.frames))
            self.counters['peak_bytes'] = max(self.counters['peak_bytes'], self.bytes)

    def pop(self):
        with self.lock:
            if not self.frames:
                return None
            value = self.frames.popleft()
            self.bytes -= len(value[2])
            self.counters['dequeued'] += 1
            return value

    def stats(self):
        with self.lock:
            return dict(self.counters, pending_frames=len(self.frames), pending_bytes=self.bytes,
                        mode=self.mode, max_frames=self.max_frames, max_bytes=self.max_bytes)
