import numpy as np
import pytest
from gymnasium import spaces

pytest.importorskip("stable_baselines3")
from omi_hil_rl.training.hil_replay import HILReplayBuffer


def test_hil_replay_samples_half_human_transitions():
    buffer = HILReplayBuffer(
        buffer_size=20,
        observation_space=spaces.Dict({"state": spaces.Box(-1, 1, shape=(2,))}),
        action_space=spaces.Box(-1, 1, shape=(1,)),
        device="cpu",
        n_envs=1,
        demo_fraction=0.5,
    )
    for i in range(10):
        obs = {"state": np.array([[float(i) / 10, 0]], dtype=np.float32)}
        next_obs = {"state": np.array([[float(i + 1) / 10, 0]], dtype=np.float32)}
        buffer.add(
            obs, next_obs, np.array([[0]], dtype=np.float32), np.array([0.0]),
            np.array([False]), [{"action_source": "human" if i == 0 else "policy"}],
        )
    indices = buffer.sample_indices(20)
    assert np.count_nonzero(indices == 0) >= 10
    assert buffer.sample(8).actions.shape == (8, 1)


def test_offline_demonstrations_do_not_enter_online_half():
    buffer = HILReplayBuffer(
        buffer_size=20,
        observation_space=spaces.Dict({"state": spaces.Box(-1, 1, shape=(2,))}),
        action_space=spaces.Box(-1, 1, shape=(1,)),
        device="cpu",
        n_envs=1,
        demo_fraction=0.5,
    )
    for i, info in enumerate([
        {"action_source": "human", "replay_origin": "offline_demo"},
        {"action_source": "human"},
        {"action_source": "policy"},
    ]):
        obs = {"state": np.array([[i / 10, 0]], dtype=np.float32)}
        buffer.add(obs, obs, np.array([[0]], dtype=np.float32), np.array([0.0]), np.array([False]), [info])
    demo, online = buffer.sample_partition_indices(20)
    assert len(demo) == len(online) == 10
    assert set(demo).issubset({0, 1})
    assert set(online).issubset({1, 2})
    assert buffer.stream_counts() == {"online": 2, "demonstration": 2, "offline_demonstration": 1}


def test_ring_overwrite_clears_old_demonstration_membership():
    buffer = HILReplayBuffer(
        buffer_size=2,
        observation_space=spaces.Dict({"state": spaces.Box(-1, 1, shape=(2,))}),
        action_space=spaces.Box(-1, 1, shape=(1,)),
        device="cpu", n_envs=1,
    )
    obs = {"state": np.zeros((1, 2), dtype=np.float32)}
    action = np.zeros((1, 1), dtype=np.float32)
    reward = np.zeros(1)
    done = np.array([False])
    buffer.add(obs, obs, action, reward, done, [{"action_source": "human", "replay_origin": "offline_demo"}])
    buffer.add(obs, obs, action, reward, done, [{"action_source": "policy"}])
    buffer.add(obs, obs, action, reward, done, [{"action_source": "policy"}])
    assert buffer.stream_counts() == {"online": 2, "demonstration": 0, "offline_demonstration": 0}
    demo, online = buffer.sample_partition_indices(8)
    assert len(demo) == 0 and len(online) == 8
