"""Defer SIGINT/SIGTERM until a complete learner update (never half an Adam step)."""
from contextlib import contextmanager
import signal


@contextmanager
def graceful_stop():
    requested = [False]

    def stop(signum, frame):
        if not requested[0]:
            print('STOP_REQUESTED: 当前完整更新结束后保存 checkpoint 并退出；请勿强制杀进程。', flush=True)
        requested[0] = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield lambda: requested[0]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
