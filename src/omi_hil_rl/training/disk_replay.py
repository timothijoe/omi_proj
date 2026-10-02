"""Single-writer disk replay with bounded batch prefetch and clean checkpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import fcntl
import json
import os
from pathlib import Path
from threading import RLock

from gymnasium import spaces
import numpy as np
from stable_baselines3.common.buffers import BaseBuffer
from stable_baselines3.common.type_aliases import DictReplayBufferSamples

from omi_hil_rl.training.hil_replay import HILReplayBuffer


class DiskHILReplayBuffer(HILReplayBuffer):
    """Store arrays in .npy files; keep at most one prefetched batch.

    Creation requires an empty directory. A process lock prevents concurrent
    writers. Only a clean checkpoint can be reopened: after the first mutation,
    the manifest is marked dirty before array contents change. This deliberately
    rejects recovery after an uncheckpointed crash rather than returning stale
    ring metadata with overwritten data. OS page caching/writeback is used;
    add() copies synchronously and does not fsync every transition.
    """

    def __init__(
        self, buffer_size, observation_space, action_space, device="auto",
        n_envs=1, optimize_memory_usage=False, handle_timeout_termination=True,
        *, directory, demo_fraction=0.5, prefetch=True,
    ):
        if n_envs != 1 or optimize_memory_usage:
            raise ValueError("disk replay requires n_envs=1 and optimize_memory_usage=False")
        if buffer_size < 1 or not isinstance(observation_space, spaces.Dict):
            raise ValueError("positive capacity and Dict observations are required")
        if not isinstance(action_space, spaces.Box):
            raise ValueError("disk replay requires Box actions")
        if any(not isinstance(s, spaces.Box) for s in observation_space.spaces.values()):
            raise ValueError("disk replay requires flat Dict of Box observations")
        if not np.isfinite(demo_fraction) or not 0 <= demo_fraction <= 1:
            raise ValueError("demo_fraction must be in [0, 1]")
        BaseBuffer.__init__(self, buffer_size, observation_space, action_space, device, n_envs=1)
        self.optimize_memory_usage = False
        self.handle_timeout_termination = handle_timeout_termination
        self.demo_fraction = float(demo_fraction)
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        if any(self.directory.iterdir()):
            raise FileExistsError(f"disk replay directory must be empty: {self.directory}")
        self._start_runtime(prefetch)
        self._specs = {}
        self._arrays = {}
        try:
            self.observations, self.next_observations = {}, {}
            for i, (key, shape) in enumerate(self.obs_shape.items()):
                for name in ("observations", "next_observations"):
                    array = self._create_array(f"{name}_{i}", (buffer_size, 1, *shape), observation_space[key].dtype)
                    getattr(self, name)[key] = array
            self.actions = self._create_array("actions", (buffer_size, 1, self.action_dim), self._maybe_cast_dtype(action_space.dtype))
            for name in ("rewards", "dones", "timeouts"):
                setattr(self, name, self._create_array(name, (buffer_size, 1), np.float32))
            for name in ("human_mask", "online_mask"):
                setattr(self, name, self._create_array(name, (buffer_size,), bool))
            self._dirty = True
            self._write_manifest(clean=False)
        except BaseException:
            self._stop_runtime()
            raise

    def _start_runtime(self, prefetch):
        self._lock = RLock()
        self._closed = False
        self.prefetch = bool(prefetch)
        self._future = None
        self._future_batch_size = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="omi-replay") if prefetch else None
        self._process_lock = (self.directory / "writer.lock").open("a+b")
        try:
            fcntl.flock(self._process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._process_lock.close()
            if self._executor:
                self._executor.shutdown()
            raise RuntimeError(f"disk replay already open by a writer: {self.directory}") from None

    def _create_array(self, name, shape, dtype):
        dtype = np.dtype(dtype)
        array = np.lib.format.open_memmap(self.directory / f"{name}.npy", mode="w+", dtype=dtype, shape=shape)
        self._specs[name] = {"shape": list(shape), "dtype": dtype.str}
        self._arrays[name] = array
        # Masks and timeouts must be defined even for unused slots. Other arrays
        # are only read after a complete transition has been published.
        if name in {"human_mask", "online_mask", "timeouts"}:
            array[:] = 0
        return array

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("disk replay is closed")

    @staticmethod
    def _space_spec(space):
        def serializable(value):
            if isinstance(value, list):
                return [serializable(v) for v in value]
            if isinstance(value, float) and not np.isfinite(value):
                return "Infinity" if value > 0 else "-Infinity"
            return value
        def bound(array):
            first = array.flat[0]
            return serializable(first.item() if np.all(array == first) else array.tolist())
        return {"shape": list(space.shape), "dtype": space.dtype.str,
                "low": bound(space.low), "high": bound(space.high)}

    def _write_manifest(self, *, clean):
        manifest = {
            "schema_version": 1, "clean": clean, "capacity": self.buffer_size,
            "pos": self.pos, "full": self.full, "demo_fraction": self.demo_fraction,
            "handle_timeout_termination": self.handle_timeout_termination,
            "arrays": self._specs,
            "observations": {k: self._space_spec(s) for k, s in self.observation_space.spaces.items()},
            "action": self._space_spec(self.action_space),
        }
        temporary = self.directory / "manifest.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.directory / "manifest.json")
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _mark_dirty(self):
        if not self._dirty:
            self._write_manifest(clean=False)
            self._dirty = True

    def add(self, obs, next_obs, action, reward, done, infos):
        with self._lock:
            self._ensure_open()
            # Validate and copy everything before changing a published ring slot.
            copied = []
            for values in (obs, next_obs):
                if set(values) != set(self.observations):
                    raise ValueError("observation keys do not match disk replay")
                item = {}
                for key, target in self.observations.items():
                    value = np.asarray(values[key], dtype=target.dtype)
                    if value.shape != target.shape[1:] or not np.isfinite(value).all():
                        raise ValueError(f"invalid observation shape or values: {key}")
                    item[key] = value.copy()
                copied.append(item)
            action = np.asarray(action, dtype=self.actions.dtype).reshape(1, self.action_dim).copy()
            reward = np.asarray(reward, dtype=np.float32).reshape(1).copy()
            done = np.asarray(done).reshape(1).copy()
            if not np.isfinite(action).all() or not np.isfinite(reward).all():
                raise ValueError("nonfinite action or reward")
            if not np.isin(done, [False, True]).all():
                raise ValueError("done must be boolean")
            if len(infos) != 1 or infos[0].get("action_source") not in {"human", "policy"}:
                raise ValueError("each transition must report human or policy action_source")
            origin = infos[0].get("replay_origin", "online")
            if origin not in {"online", "offline_demo"} or (origin == "offline_demo" and infos[0]["action_source"] != "human"):
                raise ValueError("offline_demo replay origin requires a human action")
            if not isinstance(infos[0].get("TimeLimit.truncated", False), (bool, np.bool_)):
                raise ValueError("TimeLimit.truncated must be boolean")
            self._mark_dirty()
            super().add(*copied, action, reward, done, infos)

    def _read_batch(self, batch_size, human=False):
        with self._lock:
            self._ensure_open()
            if batch_size < 1:
                raise ValueError("batch_size must be positive")
            if human:
                candidates = np.flatnonzero(self.human_mask[:self.size()])
                if not candidates.size:
                    raise RuntimeError("no human transitions available")
                indices = np.random.choice(candidates, batch_size, replace=True)
            else:
                indices = self.sample_indices(batch_size)
            # Advanced indexing copies the selected rows while holding the lock.
            return (
                {k: a[indices, 0].copy() for k, a in self.observations.items()},
                {k: a[indices, 0].copy() for k, a in self.next_observations.items()},
                self.actions[indices, 0].copy(), self.rewards[indices, 0, None].copy(),
                (self.dones[indices, 0] * (1 - self.timeouts[indices, 0]))[:, None],
            )

    def _to_samples(self, raw, env):
        obs, next_obs, actions, rewards, dones = raw
        obs = self._normalize_obs(obs, env)
        next_obs = self._normalize_obs(next_obs, env)
        return DictReplayBufferSamples(
            observations={k: self.to_torch(v) for k, v in obs.items()},
            actions=self.to_torch(actions),
            next_observations={k: self.to_torch(v) for k, v in next_obs.items()},
            dones=self.to_torch(dones), rewards=self.to_torch(self._normalize_reward(rewards, env)),
        )

    def sample(self, batch_size, env=None):
        self._ensure_open()
        if not self.prefetch:
            return self._to_samples(self._read_batch(batch_size), env)
        if self._future is not None:
            raw = self._future.result()
            matches = self._future_batch_size == batch_size
            self._future = None
            if not matches:
                raw = self._read_batch(batch_size)
        else:
            raw = self._read_batch(batch_size)
        self._future = self._executor.submit(self._read_batch, batch_size)
        self._future_batch_size = batch_size
        return self._to_samples(raw, env)

    def sample_human(self, batch_size, env=None):
        return self._to_samples(self._read_batch(batch_size, human=True), env)

    def stream_counts(self):
        with self._lock:
            self._ensure_open()
            return super().stream_counts()

    def sample_partition_indices(self, batch_size):
        with self._lock:
            self._ensure_open()
            return super().sample_partition_indices(batch_size)

    def reset(self):
        with self._lock:
            self._ensure_open()
            if self._future is not None:
                # Do not wait on a worker while holding its lock.
                self._future.cancel()
                self._future = None
            self._mark_dirty()
            self.pos, self.full = 0, False
            self.human_mask[:] = False
            self.online_mask[:] = False

    def checkpoint(self):
        """Flush arrays and atomically publish ring metadata. Call at a safe pause."""
        with self._lock:
            self._ensure_open()
            for name, array in self._arrays.items():
                array.flush()
                with (self.directory / f"{name}.npy").open("rb") as stream:
                    os.fsync(stream.fileno())
            self._write_manifest(clean=True)
            self._dirty = False
        return self.directory / "manifest.json"

    @classmethod
    def reopen(cls, directory, *, device="cpu", prefetch=True):
        """Reopen the last clean checkpoint without allocating capacity in RAM."""
        self = cls.__new__(cls)
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise FileNotFoundError(self.directory)
        self._start_runtime(prefetch)
        try:
            manifest = json.loads((self.directory / "manifest.json").read_text())
            if manifest.get("schema_version") != 1 or not manifest.get("clean"):
                raise ValueError("disk replay has no clean checkpoint; uncheckpointed recovery is unsupported")
            def box(spec):
                dtype = np.dtype(spec["dtype"])
                low, high = np.asarray(spec["low"], dtype=dtype), np.asarray(spec["high"], dtype=dtype)
                return spaces.Box(low.item() if low.ndim == 0 else low, high.item() if high.ndim == 0 else high,
                                  shape=tuple(spec["shape"]), dtype=dtype)
            observation_space = spaces.Dict(OrderedDict((k, box(s)) for k, s in manifest["observations"].items()))
            BaseBuffer.__init__(self, manifest["capacity"], observation_space, box(manifest["action"]), device, n_envs=1)
            self.pos, self.full = manifest["pos"], manifest["full"]
            self.demo_fraction = manifest["demo_fraction"]
            self.handle_timeout_termination = manifest["handle_timeout_termination"]
            self.optimize_memory_usage = False
            self._specs, self._arrays = manifest["arrays"], {}
            for name, spec in self._specs.items():
                if not name.replace("_", "").isalnum():
                    raise ValueError("invalid array filename")
                array = np.load(self.directory / f"{name}.npy", mmap_mode="r+", allow_pickle=False)
                if list(array.shape) != spec["shape"] or array.dtype.str != spec["dtype"]:
                    raise ValueError(f"disk replay array schema mismatch: {name}")
                self._arrays[name] = array
            self.observations, self.next_observations = {}, {}
            for i, key in enumerate(self.obs_shape):
                self.observations[key] = self._arrays[f"observations_{i}"]
                self.next_observations[key] = self._arrays[f"next_observations_{i}"]
            for name in ("actions", "rewards", "dones", "timeouts", "human_mask", "online_mask"):
                setattr(self, name, self._arrays[name])
            if not 0 <= self.pos < self.buffer_size:
                raise ValueError("invalid disk replay ring position")
            self._dirty = False
            return self
        except BaseException:
            self._stop_runtime()
            raise

    def storage_stats(self):
        return {"backend": "disk", "capacity": self.buffer_size, "size": self.size(),
                "array_bytes": sum(a.nbytes for a in self._arrays.values()),
                "prefetch_batches": int(self.prefetch), "directory": str(self.directory)}

    def __getstate__(self):
        raise TypeError("disk replay must be saved with checkpoint(), not pickled; use reopen() to restore")

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _stop_runtime(self):
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        if not self._process_lock.closed:
            self._process_lock.close()
        self._closed = True
        for array in getattr(self, "_arrays", {}).values():
            array._mmap.close()

    def close(self):
        if self._closed:
            return
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        self._future = None
        try:
            self.checkpoint()
        finally:
            self._stop_runtime()
