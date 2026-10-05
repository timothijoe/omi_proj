"""Disk storage and streaming import for complete, versioned HIL transitions.

This is a data API, not a robot actor or an RL learner. BC proxy targets are
deliberately not accepted as executed commands.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gymnasium import spaces
import numpy as np

from .disk_replay import DiskHILReplayBuffer


CONTRACT_KEYS = ("observation_contract", "action_contract", "reward_contract", "action_semantics")
METADATA = {
    "transition_episode": "S128",
    "transition_step": "int64",
    "observation_time_ns": "int64",
    "next_observation_time_ns": "int64",
}


def _box(spec):
    dtype = np.dtype(spec["dtype"])
    shape = tuple(spec["shape"])
    if not shape or any(type(n) is not int or n < 1 for n in shape):
        raise ValueError("space shape must contain positive integers")
    if dtype.kind not in "fu":
        raise ValueError("only float and unsigned integer arrays are supported")
    low, high = np.asarray(spec["low"], dtype=dtype), np.asarray(spec["high"], dtype=dtype)
    return spaces.Box(low.item() if low.ndim == 0 else low,
                      high.item() if high.ndim == 0 else high, shape=shape, dtype=dtype)


def _spaces(contract):
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported transition contract schema")
    for key in CONTRACT_KEYS:
        if not isinstance(contract.get(key), str) or not contract[key]:
            raise ValueError(f"missing {key}")
    if contract["action_semantics"] != "accepted_command":
        raise ValueError("replay requires accepted_command, not future-state proxy labels")
    if not contract.get("observations"):
        raise ValueError("observations must not be empty")
    observation = spaces.Dict({k: _box(v) for k, v in contract["observations"].items()})
    action = _box(contract["action"])
    if len(action.shape) != 1 or action.dtype.kind != "f":
        raise ValueError("action must be a floating-point vector")
    return observation, action


def _array(value, space, name):
    raw = np.asarray(value)
    if raw.shape != space.shape or raw.dtype.kind not in "iuf" or not np.isfinite(raw).all():
        raise ValueError(f"invalid {name}: shape or nonfinite/nonnumeric values")
    # Validate before casting: uint8 conversion must not wrap or truncate pixels.
    if np.any(raw < space.low) or np.any(raw > space.high):
        raise ValueError(f"invalid {name}: outside configured bounds")
    if space.dtype.kind == "u" and np.any(raw != np.floor(raw)):
        raise ValueError(f"invalid {name}: noninteger image values")
    converted = raw.astype(space.dtype)
    if not np.isfinite(converted).all():
        raise ValueError(f"invalid {name}: dtype overflow")
    return converted


def _integer(value, name, minimum):
    if type(value) is not int or not minimum <= value <= np.iinfo(np.int64).max:
        raise ValueError(f"invalid {name}")
    return value


class TransitionReplay:
    """One writer; disk arrays plus at most one prefetched training batch.

    Contract, episode/step and observation times are persisted alongside the
    ring. Offline demos are demo-only; online human steps belong to both flows.
    sample() returns the existing SB3 batch format. It does not normalize physical
    actions or construct a compatible learner.
    """

    def __init__(self, directory, contract, capacity, *, prefetch=True, demo_fraction=0.5):
        observation, action = _spaces(contract)
        # Store a JSON-owned copy so callers cannot change the active contract.
        self.contract = json.loads(json.dumps(contract, allow_nan=False))
        self.buffer = DiskHILReplayBuffer(
            capacity, observation, action, directory=directory, device="cpu",
            prefetch=prefetch, demo_fraction=demo_fraction,
        )
        try:
            for name, dtype in METADATA.items():
                self.buffer._create_array(name, (capacity,), dtype)
            (self.buffer.directory / "transition_contract.json").write_text(
                json.dumps(self.contract, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            self.buffer.checkpoint()
        except BaseException:
            self.buffer._stop_runtime()
            raise

    @classmethod
    def reopen(cls, directory, *, expected_contract=None, prefetch=True):
        self = cls.__new__(cls)
        self.contract = json.loads((Path(directory) / "transition_contract.json").read_text())
        observation, action = _spaces(self.contract)
        if expected_contract is not None and self.contract != expected_contract:
            raise ValueError("transition contract mismatch")
        self.buffer = DiskHILReplayBuffer.reopen(directory, device="cpu", prefetch=prefetch)
        try:
            if self.buffer.observation_space != observation or self.buffer.action_space != action:
                raise ValueError("transition contract and replay spaces disagree")
            for name, dtype in METADATA.items():
                array = self.buffer._arrays[name]
                if array.shape != (self.buffer.buffer_size,) or array.dtype != np.dtype(dtype):
                    raise ValueError(f"invalid metadata array: {name}")
        except BaseException:
            self.buffer._stop_runtime()
            raise
        return self

    def validate(self, record, *, origin="online"):
        """Validate without modifying replay; used before importing an episode."""
        if origin not in {"online", "offline_demo"}:
            raise ValueError("unknown replay origin")
        for key in CONTRACT_KEYS:
            if record.get(key) != self.contract[key]:
                raise ValueError(f"transition {key} mismatch or missing")
        source = record.get("action_source")
        if source not in {"policy", "human"}:
            raise ValueError("action_source must be human or policy; paused steps need separate handling")
        if origin == "offline_demo" and (source != "human" or record.get("episode_success") is not True):
            raise ValueError("initial offline demos require human actions and confirmed episode_success=true")
        episode = record.get("episode")
        if not isinstance(episode, str) or not episode or len(episode.encode("utf-8")) > 128 or "\x00" in episode:
            raise ValueError("episode must be a nonempty UTF-8 ID of at most 128 bytes")
        step = _integer(record.get("step"), "step", 0)
        stamp = _integer(record.get("observation_time_ns"), "observation_time_ns", 1)
        next_stamp = _integer(record.get("next_observation_time_ns"), "next_observation_time_ns", 1)
        if next_stamp <= stamp:
            raise ValueError("next observation must follow current observation")
        terminated, truncated = record.get("terminated"), record.get("truncated")
        if type(terminated) is not bool or type(truncated) is not bool:
            raise ValueError("terminated and truncated must be booleans")
        reward = record.get("reward")
        if type(reward) not in {float, int} or not np.isfinite(reward) or abs(reward) > np.finfo(np.float32).max:
            raise ValueError("reward must be finite and representable as float32")
        observations = []
        for name in ("observation", "next_observation"):
            values = record.get(name)
            if not isinstance(values, dict) or set(values) != set(self.buffer.observation_space.spaces):
                raise ValueError(f"{name} keys mismatch or missing")
            observations.append({
                key: _array(values[key], space, f"{name}.{key}")[None]
                for key, space in self.buffer.observation_space.spaces.items()
            })
        action = _array(record.get("executed_action"), self.buffer.action_space, "executed_action")
        metadata = dict(transition_episode=episode.encode("utf-8"), transition_step=step,
                        observation_time_ns=stamp, next_observation_time_ns=next_stamp)
        return observations, action, metadata, reward, terminated, truncated, source

    def append(self, record, *, origin="online"):
        """Validate a complete transition, then publish it to the disk ring."""
        observations, action, metadata, reward, terminated, truncated, source = self.validate(record, origin=origin)
        with self.buffer._lock:
            slot = self.buffer.pos
            self.buffer.add(
                *observations, action[None], np.asarray([reward], np.float32),
                np.asarray([terminated or truncated]), [{"action_source": source,
                    "replay_origin": origin, "TimeLimit.truncated": truncated and not terminated}],
            )
            for name, value in metadata.items():
                self.buffer._arrays[name][slot] = value
        return slot

    def import_jsonl(self, path, *, origin):
        """Stream one record at a time; on error, earlier valid rows remain saved."""
        count = 0
        with Path(path).open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("transition must be an object")
                    self.append(record, origin=origin)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}; {count} earlier rows accepted") from exc
                count += 1
        return count

    def metadata(self, slot):
        with self.buffer._lock:
            self.buffer._ensure_open()
            if type(slot) is not int or not 0 <= slot < self.buffer.size():
                raise IndexError("slot outside retained replay")
            return {"episode": self.buffer._arrays["transition_episode"][slot].decode("utf-8"),
                    "step": int(self.buffer._arrays["transition_step"][slot]),
                    **{name: int(self.buffer._arrays[name][slot]) for name in
                       ("observation_time_ns", "next_observation_time_ns")},
                    "action_source": "human" if self.buffer.human_mask[slot] else "policy",
                    "replay_origin": "online" if self.buffer.online_mask[slot] else "offline_demo"}

    def report(self):
        return {**self.buffer.storage_stats(), "streams": self.buffer.stream_counts(),
                "contract": self.contract}

    def close(self):
        self.buffer.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "append", "inspect"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--contract", type=Path, help="Required to create; otherwise checks exact compatibility")
    parser.add_argument("--capacity", type=int, help="Ring capacity; required to create")
    parser.add_argument("--offline-demo", type=Path, action="append", default=[])
    parser.add_argument("--online", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.operation == "create" and (args.contract is None or args.capacity is None or args.capacity < 1):
        parser.error("create requires --contract and positive --capacity")
    if args.operation != "create" and args.capacity is not None:
        parser.error("capacity cannot be changed for an existing replay")
    if args.operation == "inspect" and (args.offline_demo or args.online):
        parser.error("inspect does not import data")
    contract = json.loads(args.contract.read_text()) if args.contract else None
    try:
        replay = (TransitionReplay(args.directory, contract, args.capacity, prefetch=False)
                  if args.operation == "create" else
                  TransitionReplay.reopen(args.directory, expected_contract=contract, prefetch=False))
        with replay:
            imported = {"offline_demo": 0, "online": 0}
            for origin, paths in (("offline_demo", args.offline_demo), ("online", args.online)):
                for path in paths:
                    imported[origin] += replay.import_jsonl(path, origin=origin)
            print(json.dumps({**replay.report(), "imported": imported}, indent=2))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
