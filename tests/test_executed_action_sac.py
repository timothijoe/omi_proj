import numpy as np
import pytest

pytest.importorskip("stable_baselines3")

from omi_hil_rl.sim.intervention import ScriptedInterventionWrapper
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv
from omi_hil_rl.training.executed_action_sac import ExecutedActionSAC


def test_replay_contains_human_action_when_policy_is_overridden():
    env = ScriptedInterventionWrapper(
        TianjiSurrogateEnv(), lambda _: np.ones(7, dtype=np.float32), probability=1.0
    )
    model = ExecutedActionSAC(
        "MultiInputPolicy", env, learning_starts=100, buffer_size=100,
        policy_kwargs={"net_arch": [16, 16]}, seed=0, device="cpu"
    )
    model.learn(total_timesteps=8)
    np.testing.assert_allclose(model.replay_buffer.actions[:8], np.ones((8, 1, 7)))
    env.close()
