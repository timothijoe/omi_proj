import numpy as np

from omi_hil_rl.sim.intervention import ScriptedInterventionWrapper, joint_goal_teacher
from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


def test_scripted_teacher_overrides_policy_and_can_be_turned_off():
    base = TianjiSurrogateEnv()
    teacher = joint_goal_teacher(base.goal_rad, base.max_delta_rad)
    env = ScriptedInterventionWrapper(base, teacher, probability=1.0)
    env.reset()
    _, _, _, _, info = env.step(np.zeros(7))
    assert info["action_source"] == "human"
    assert info["executed_action"][0] > 0
    env.set_probability(0.0)
    _, _, _, _, info = env.step(np.zeros(7))
    assert info["action_source"] == "policy"
    np.testing.assert_allclose(info["executed_action"], np.zeros(7))
    env.close()
