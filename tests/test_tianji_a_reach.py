import os
from pathlib import Path

import numpy as np
import pytest

from omi_hil_rl.sim.intervention import joint_goal_teacher
from omi_hil_rl.sim.keyboard_teleop import parse_jog
from omi_hil_rl.sim.tianji_a_reach import TianjiAReachEnv


def test_keyboard_jog_maps_one_joint_and_rejects_bad_input():
    assert np.array_equal(parse_jog("3-"), np.array([0, 0, -1, 0, 0, 0, 0]))
    assert np.array_equal(parse_jog(""), np.zeros(7))
    assert parse_jog("8+") is None
    assert parse_jog("1++") is None


@pytest.mark.skipif(not os.environ.get("OMI_TIANJI_SCENE"), reason="external MJCF not configured")
def test_real_scene_a_reach_and_action_provenance():
    env = TianjiAReachEnv(scene=Path(os.environ["OMI_TIANJI_SCENE"]))
    try:
        observation, info = env.reset(seed=0)
        assert info["model_kind"] == "cooking_marvin_dual_arm_scene_A"
        assert env.observation_space.contains(observation)
        teacher = joint_goal_teacher(env.goal_rad, env.max_delta_rad)
        for _ in range(20):
            action = teacher(observation)
            observation, _, done, truncated, step_info = env.step(
                np.zeros(7), intervention_active=True, human_action=action
            )
            assert step_info["action_source"] == "human"
            assert np.allclose(step_info["human_action"], action)
            if done or truncated:
                break
        assert done and not truncated
        assert step_info["tcp_error_m"] <= env.success_tolerance_m
    finally:
        env.close()
