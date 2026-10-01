import numpy as np

from omi_hil_rl.sim.interactive_rollout import step_with_command
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


def test_policy_and_keyboard_intervention_share_one_step_path():
    env = TianjiSurrogateEnv()
    try:
        env.reset(seed=0)
        policy = -np.ones(7, dtype=np.float32)
        _, _, _, _, info = step_with_command(env, policy, "1+")
        assert info["action_source"] == "human"
        assert info["policy_action"][0] == -1
        assert info["human_action"][0] == 1
        assert info["executed_action"][0] == 1
        _, _, _, _, info = step_with_command(env, policy, "")
        assert info["action_source"] == "policy"
        assert info["executed_action"][0] == -1
    finally:
        env.close()
