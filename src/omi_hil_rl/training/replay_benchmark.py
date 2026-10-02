"""Measure disk replay writes and cached random batch sampling with RGB images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
from time import perf_counter

from gymnasium import spaces
import numpy as np

from omi_hil_rl.training.disk_replay import DiskHILReplayBuffer


def benchmark(directory: Path, *, capacity=512, transitions=1024, batches=100, batch_size=64):
    if min(capacity, transitions, batches, batch_size) < 1:
        raise ValueError("all benchmark counts must be positive")
    observation_space = spaces.Dict({
        "state": spaces.Box(-np.inf, np.inf, (19,), dtype=np.float32),
        **{f"camera_{i}": spaces.Box(0, 255, (128, 128, 3), dtype=np.uint8) for i in range(3)},
    })
    buffer = DiskHILReplayBuffer(capacity, observation_space, spaces.Box(-1, 1, (7,), dtype=np.float32),
                                 device="cpu", directory=directory)
    rng = np.random.default_rng(0)
    obs = {key: rng.integers(0, 255, (1, *space.shape), dtype=np.uint8) if key != "state"
           else np.zeros((1, 19), np.float32) for key, space in observation_space.spaces.items()}
    next_obs = {key: value.copy() for key, value in obs.items()}
    timings = []
    try:
        start = perf_counter()
        for i in range(transitions):
            buffer.add(obs, next_obs, np.zeros((1, 7), np.float32), np.array([0]), np.array([False]),
                       [{"action_source": "human" if i % 5 == 0 else "policy"}])
        write_seconds = perf_counter() - start
        start = perf_counter()
        buffer.checkpoint()
        flush_seconds = perf_counter() - start
        buffer.sample(batch_size)
        start = perf_counter()
        for _ in range(batches):
            tick = perf_counter()
            buffer.sample(batch_size)
            timings.append(perf_counter() - tick)
        sample_seconds = perf_counter() - start
        result = {
            **buffer.storage_stats(), "transitions_written": transitions,
            "write_seconds": write_seconds, "writes_per_second": transitions / write_seconds,
            "checkpoint_seconds": flush_seconds, "batches": batches, "batch_size": batch_size,
            "sample_seconds": sample_seconds, "batches_per_second": batches / sample_seconds,
            "sample_p50_ms": float(np.percentile(timings, 50) * 1000),
            "sample_p95_ms": float(np.percentile(timings, 95) * 1000),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "conditions": "CPU batches; three 128x128 RGB uint8 views; OS page cache retained; not a cold-disk or GPU benchmark",
        }
    finally:
        buffer.close()
    (directory / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="Empty directory for benchmark data")
    parser.add_argument("--capacity", type=int, default=512)
    parser.add_argument("--transitions", type=int, default=1024)
    parser.add_argument("--batches", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.directory, capacity=args.capacity, transitions=args.transitions,
                               batches=args.batches, batch_size=args.batch_size), indent=2))


if __name__ == "__main__":
    main()
