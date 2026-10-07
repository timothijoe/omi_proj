"""Defer SIGINT/SIGTERM until a complete learner update (never half an Adam step)."""
from contextlib import contextmanager
import signal
from pathlib import Path


def interpreter_path(path):
    """Keep the venv path: resolving its symlink would discard pyvenv.cfg."""
    executable = Path(path).absolute()
    if not executable.is_file():
        raise ValueError('learner interpreter missing: ' + str(executable))
    return str(executable)


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
