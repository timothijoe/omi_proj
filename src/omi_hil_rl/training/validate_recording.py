"""Check saved simulation transitions for action provenance and continuity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def validate_recording(path: Path) -> dict[str, int]:
    count = 0
    interventions = 0
    completed = 0
    previous = None
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = json.loads(line)
            try:
                source = record["action_source"]
                policy = np.asarray(record["policy_action"], dtype=float)
                executed = np.asarray(record["executed_action"], dtype=float)
                human = record["human_action"]
                state = np.asarray(record["observation"]["state"], dtype=float)
                next_state = np.asarray(record["next_observation"]["state"], dtype=float)
                episode = int(record["episode"])
                step = int(record["step"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"line {line_number}: invalid transition schema") from exc
            if (source not in {"human", "policy"} or policy.shape != (7,) or executed.shape != (7,)
                    or state.shape != (14,) or next_state.shape != (14,)
                    or not all(np.all(np.isfinite(x)) for x in (policy, executed, state, next_state))):
                raise ValueError(f"line {line_number}: invalid action or state")
            if source == "human":
                if human is None or np.asarray(human).shape != (7,):
                    raise ValueError(f"line {line_number}: human action missing")
                interventions += 1
            elif human is not None:
                raise ValueError(f"line {line_number}: policy transition has human action")
            if previous is not None and episode == previous["episode"]:
                if step != previous["step"] + 1 or not np.allclose(state, previous["next_state"], atol=1e-6):
                    raise ValueError(f"line {line_number}: episode state continuity broken")
            previous = {"episode": episode, "step": step, "next_state": next_state}
            count += 1
            completed += bool(record["terminated"] or record["truncated"])
    if count == 0:
        raise ValueError("recording is empty")
    return {"transitions": count, "interventions": interventions, "completed_episodes": completed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_recording(args.recording), indent=2))


if __name__ == "__main__":
    main()
