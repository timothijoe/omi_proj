import json

import numpy as np

from omi_hil_rl.sim.intervention import ScriptedInterventionWrapper
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv
from omi_hil_rl.training.recording import TransitionRecorder
from omi_hil_rl.training.validate_recording import validate_recording


def test_recording_preserves_policy_and_executed_action_provenance(tmp_path):
    intervention = ScriptedInterventionWrapper(
        TianjiSurrogateEnv(), lambda _: np.ones(7, dtype=np.float32), probability=1.0
    )
    path = tmp_path / "transitions.jsonl"
    env = TransitionRecorder(intervention, path)
    env.reset()
    env.step(np.zeros(7))
    env.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["action_source"] == "human"
    assert record["policy_action"] == [0.0] * 7
    assert record["executed_action"] == [1.0] * 7
    assert len(record["observation"]["state"]) == 14
    assert record["next_observation"]["state"][0] > 0
    assert validate_recording(path) == {"transitions": 1, "interventions": 1, "completed_episodes": 0}
