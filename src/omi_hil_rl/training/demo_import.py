"""Import recorded human actions into the simulation replay buffer."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from omi_hil_rl.training.validate_recording import validate_recording


def import_human_demonstrations(model, path: Path, expected_model_kind: str) -> int:
    validate_recording(path)
    imported = 0
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = json.loads(line)
            if record["action_source"] != "human":
                continue
            if record.get("model_kind") != expected_model_kind:
                raise ValueError(f"line {line_number}: demonstration model does not match training model")
            observation = {key: np.asarray(value, dtype=np.float32) for key, value in record["observation"].items()}
            next_observation = {
                key: np.asarray(value, dtype=np.float32) for key, value in record["next_observation"].items()
            }
            if not model.observation_space.contains(observation) or not model.observation_space.contains(next_observation):
                raise ValueError(f"line {line_number}: demonstration observation is outside the training space")
            action = np.asarray(record["executed_action"], dtype=np.float32)
            if action.shape != (7,) or not np.all(np.isfinite(action)) or np.any(np.abs(action) > 1.000001):
                raise ValueError(f"line {line_number}: invalid executed action")
            truncated = bool(record["truncated"])
            done = bool(record["terminated"] or truncated)
            model.replay_buffer.add(
                {key: value[None, ...] for key, value in observation.items()},
                {key: value[None, ...] for key, value in next_observation.items()},
                action[None, ...],
                np.asarray([record["reward"]], dtype=np.float32),
                np.asarray([done]),
                [{"action_source": "human", "replay_origin": "offline_demo", "TimeLimit.truncated": truncated}],
            )
            imported += 1
    if not imported:
        raise ValueError("recording contains no human demonstrations")
    return imported
