"""Single-host episode handoff; actor stages on disk, learner owns replay writes."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import uuid

import numpy as np
import torch

from omi_hil_rl.training.transition_replay import CONTRACT_KEYS
from .networks import VERSION


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def atomic_torch(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("wb") as stream:
        torch.save(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def owner_lock(directory, role):
    """Fail immediately if another writer already owns this run/role."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (role + ".lock")).open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another " + role + " owns this run") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class EpisodeSpool:
    def __init__(self, run, episode, contract, *, origin="online", policy_version=0):
        if origin not in ("online", "offline_demo"):
            raise ValueError("unknown origin")
        self.directory = Path(run) / "episodes" / episode
        self.directory.mkdir(parents=True, exist_ok=False)
        self.contract, self.episode, self.origin = contract, episode, origin
        self.count = 0
        self.last = None
        self.metadata = dict(episode=episode, contract=contract, origin=origin, policy_version=policy_version)
        atomic_json(self.directory / "staging.json", self.metadata)

    def append(self, observation, next_observation, reward, terminated, truncated, info):
        if self.last is not None and (self.last["terminated"] or self.last["truncated"]):
            raise ValueError("cannot append after episode termination")
        if info["episode"] != self.episode or info["step"] != self.count:
            raise ValueError("episode or step mismatch")
        metadata = {k: self.contract[k] for k in CONTRACT_KEYS}
        metadata.update(episode=self.episode, step=self.count, reward=float(reward),
            terminated=bool(terminated), truncated=bool(truncated),
            observation_time_ns=int(info["observation_time_ns"]), next_observation_time_ns=int(info["next_observation_time_ns"]),
            action_source=info["action_source"], command_status=info["command_status"], episode_success=bool(terminated))
        arrays = {"observation__" + k: v for k, v in observation.items()}
        arrays.update({"next_observation__" + k: v for k, v in next_observation.items()})
        arrays.update(executed_action=info["executed_action"], metadata=np.asarray(json.dumps(metadata)))
        destination = self.directory / f"{self.count:06d}.npz"
        with destination.with_suffix(".tmp").open("wb") as stream:
            np.savez_compressed(stream, **arrays)
        destination.with_suffix(".tmp").replace(destination)
        self.count += 1
        self.last = metadata

    def truncate_valid_prefix(self):
        """Timeout between commands: relabel the existing final step, add no action."""
        if self.last is None or self.last["terminated"] or self.last["truncated"]:
            raise ValueError("an unfinished nonempty valid prefix is required")
        destination = self.directory / f"{self.count - 1:06d}.npz"
        with np.load(destination, allow_pickle=False) as archive:
            arrays = {key: archive[key].copy() for key in archive.files}
        metadata = json.loads(str(arrays["metadata"]))
        metadata.update(truncated=True, episode_success=False, timeout_between_commands=True)
        arrays["metadata"] = np.asarray(json.dumps(metadata))
        with destination.with_suffix(".tmp").open("wb") as stream:
            np.savez_compressed(stream, **arrays)
        destination.with_suffix(".tmp").replace(destination)
        self.last = metadata

    def finish(self, keep, *, reason=None):
        complete = self.last is not None and (self.last["terminated"] or self.last["truncated"])
        if keep and not complete:
            raise ValueError("incomplete episode cannot enter replay")
        metadata = dict(self.metadata, count=self.count, keep=bool(keep),
                        episode_success=bool(self.last and self.last["terminated"]), reason=reason)
        if keep and self.origin == "offline_demo":
            if not metadata["episode_success"]:
                raise ValueError("initial offline demo must be successful")
            for record in read_episode(self.directory, metadata):
                if record["action_source"] != "human":
                    raise ValueError("offline demo contains policy actions")
        atomic_json(self.directory / ("ready.json" if keep else "discarded.json"), metadata)
        return metadata


def read_episode(directory, manifest):
    directory = Path(directory)
    previous = None
    for index in range(manifest["count"]):
        with np.load(directory / f"{index:06d}.npz", allow_pickle=False) as arrays:
            record = json.loads(str(arrays["metadata"]))
            for name in ("observation", "next_observation"):
                prefix = name + "__"
                record[name] = {k[len(prefix):]: arrays[k].copy() for k in arrays.files if k.startswith(prefix)}
            record["executed_action"] = arrays["executed_action"].copy()
        if record["step"] != index or record["episode"] != manifest["episode"]:
            raise ValueError("spool episode or step mismatch")
        if previous is not None and (record["observation_time_ns"] != previous["next_observation_time_ns"]
            or previous["terminated"] or previous["truncated"]):
            raise ValueError("spool transition chronology mismatch")
        previous = record
        record["episode_success"] = manifest["episode_success"]
        yield record
    if previous is None or not (previous["terminated"] or previous["truncated"]):
        raise ValueError("spool has no final transition")


def import_ready(run, replay):
    """Clean checkpoint before receipt; journal detects interruption/duplicates.

    A dirty replay after a process crash is deliberately refused by disk_replay;
    no automatic partial-write recovery is claimed. With a clean checkpoint the
    pending journal verifies every imported slot before completing its receipt.
    """
    run = Path(run)
    journal = run / "import_pending.json"
    if journal.exists():
        pending = json.loads(journal.read_text())
        slots = [(pending["start"] + i) % replay.buffer.buffer_size for i in range(pending["count"])]
        if not all(replay.metadata(slot)["episode"] == pending["episode"] and
                   replay.metadata(slot)["step"] == i for i, slot in enumerate(slots)):
            raise RuntimeError("unfinished import; restore a clean replay backup before resuming")
        atomic_json(Path(pending["directory"]) / "imported.json", pending)
        journal.unlink()
    imported = 0
    for ready in sorted((run / "episodes").glob("*/ready.json")):
        if (ready.parent / "imported.json").exists():
            continue
        manifest = json.loads(ready.read_text())
        if manifest["contract"] != replay.contract or not manifest["keep"]:
            raise ValueError("episode handoff contract mismatch")
        if not 1 <= manifest["count"] <= replay.buffer.buffer_size:
            raise ValueError("episode exceeds replay capacity")
        # Validate the complete stream before modifying the destination ring.
        for record in read_episode(ready.parent, manifest):
            replay.validate(record, origin=manifest["origin"])
        pending = dict(directory=str(ready.parent.resolve()), episode=manifest["episode"],
                       count=manifest["count"], start=replay.buffer.pos)
        atomic_json(journal, pending)
        for record in read_episode(ready.parent, manifest):
            replay.append(record, origin=manifest["origin"])
        replay.buffer.checkpoint()
        atomic_json(ready.parent / "imported.json", pending)
        journal.unlink()
        imported += manifest["count"]
    return imported


def publish(run, agent):
    run = Path(run)
    atomic_torch(run / "learner.pt", agent.checkpoint())
    atomic_torch(run / "actor.pt", dict(version=VERSION, recipe=agent.recipe,
        contract=agent.contract, updates=agent.updates, actor=agent.actor.state_dict()))
