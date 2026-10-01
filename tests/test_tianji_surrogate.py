import numpy as np
import pytest

from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


def test_reset_and_policy_step_have_expected_contract():
    env = TianjiSurrogateEnv()
    obs, reset_info = env.reset()
    assert env.observation_space.contains(obs)
    assert reset_info["model_kind"] == "uncalibrated_7dof_surrogate"
    next_obs, reward, terminated, truncated, info = env.step(np.array([1, 0, 0, 0, 0, 0, 0]))
    assert env.observation_space.contains(next_obs)
    assert next_obs["state"][0] > obs["state"][0]
    assert reward == 0.0 and not terminated and not truncated
    assert info["action_source"] == "policy"
    np.testing.assert_allclose(info["executed_action"], [1, 0, 0, 0, 0, 0, 0])
    env.close()


def test_human_intervention_records_commanded_action_instead_of_policy_action():
    env = TianjiSurrogateEnv()
    policy = np.array([-1, 0, 0, 0, 0, 0, 0])
    human = np.array([1, 0, 0, 0, 0, 0, 0])
    _, _, _, _, info = env.step(policy, intervention_active=True, human_action=human)
    assert info["action_source"] == "human"
    np.testing.assert_allclose(info["policy_action"], policy)
    np.testing.assert_allclose(info["human_action"], human)
    np.testing.assert_allclose(info["executed_action"], human)
    assert info["commanded_joint_target_rad"][0] > 0
    env.close()


def test_joint_limit_changes_recorded_executed_action():
    env = TianjiSurrogateEnv()
    joint = 0
    limit = env.joint_limits[joint, 1]
    env.data.qpos[env.qpos_ids[joint]] = limit - 0.01
    env.data.ctrl[env.actuator_ids[joint]] = limit - 0.01
    _, _, _, _, info = env.step(np.array([1, 0, 0, 0, 0, 0, 0]))
    assert info["commanded_joint_target_rad"][joint] == pytest.approx(limit)
    assert info["executed_action"][joint] == pytest.approx(0.25)
    env.close()


@pytest.mark.parametrize("action", [[float("nan")] * 7, [2.0] + [0.0] * 6, [0.0] * 6])
def test_unsafe_action_rejected_before_simulation_advances(action):
    env = TianjiSurrogateEnv()
    before = env.data.time
    with pytest.raises(ValueError):
        env.step(np.array(action))
    assert env.data.time == before
    env.close()


def test_timeout_and_reset():
    env = TianjiSurrogateEnv(max_steps=1)
    _, reward, terminated, truncated, _ = env.step(np.zeros(7))
    assert reward == 0.0 and not terminated and truncated
    with pytest.raises(RuntimeError, match="reset"):
        env.step(np.zeros(7))
    env.reset()
    assert env.data.time == 0.0
    env.close()


def test_goal_terminates_with_sparse_reward():
    env = TianjiSurrogateEnv(goal_rad=(0, 0, 0, 0, 0, 0, 0))
    _, reward, terminated, truncated, _ = env.step(np.zeros(7))
    assert reward == 1.0 and terminated and not truncated
    env.close()


def test_randomized_reset_is_bounded_and_reproducible():
    env = TianjiSurrogateEnv(reset_noise_rad=0.03)
    first, _ = env.reset(seed=123)
    second, _ = env.reset(seed=123)
    np.testing.assert_allclose(first["state"], second["state"])
    assert np.max(np.abs(first["state"][:7])) <= 0.03
    assert not np.allclose(first["state"][:7], 0)
    env.close()


def test_full_episode_reaches_goal_after_one_human_override():
    env = TianjiSurrogateEnv()
    obs, _ = env.reset()
    sources = []
    for step in range(env.max_steps):
        policy = np.clip((env.goal_rad - obs["state"][:7]) / env.max_delta_rad, -1, 1)
        intervening = step == 2
        obs, reward, terminated, truncated, info = env.step(
            policy,
            intervention_active=intervening,
            human_action=np.zeros(7) if intervening else None,
        )
        sources.append(info["action_source"])
        if intervening:
            np.testing.assert_allclose(info["executed_action"], np.zeros(7))
        if terminated or truncated:
            break
    assert sources.count("human") == 1
    assert terminated and not truncated and reward == 1.0
    env.close()
