import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from gymnasium import spaces
import numpy as np
import pytest

pytest.importorskip("stable_baselines3")
from omi_hil_rl.training.disk_replay import DiskHILReplayBuffer
from omi_hil_rl.training.hil_replay import HILReplayBuffer


def make_buffer(directory, capacity=4, prefetch=True):
    return DiskHILReplayBuffer(
        capacity, spaces.Dict({
            "state": spaces.Box(-100, 100, shape=(2,), dtype=np.float32),
            "image": spaces.Box(0, 255, shape=(8, 8, 3), dtype=np.uint8),
        }), spaces.Box(-1, 1, shape=(1,), dtype=np.float32),
        device="cpu", directory=directory, prefetch=prefetch,
    )


def insert(buffer, value, source="policy", origin="online", timeout=False):
    obs = {"state": np.full((1, 2), value, np.float32), "image": np.full((1, 8, 8, 3), value, np.uint8)}
    next_obs = {"state": obs["state"] + 1, "image": obs["image"] + 1}
    buffer.add(obs, next_obs, np.array([[value / 100]], np.float32), np.array([value]),
               np.array([timeout]), [{"action_source": source, "replay_origin": origin, "TimeLimit.truncated": timeout}])


def assert_consistent(batch):
    state = batch.observations["state"].numpy()
    image = batch.observations["image"].numpy()
    assert np.all(image == state[:, 0, None, None, None])
    assert np.array_equal(batch.next_observations["state"].numpy(), state + 1)
    assert np.all(batch.next_observations["image"].numpy() == image + 1)
    assert np.array_equal(batch.rewards.numpy()[:, 0], state[:, 0])


def test_disk_arrays_and_overwrite_match_memory(tmp_path):
    disk = make_buffer(tmp_path / "replay", prefetch=False)
    memory = HILReplayBuffer(4, disk.observation_space, disk.action_space, device="cpu")
    try:
        assert isinstance(disk.observations["image"], np.memmap)
        for i in range(9):
            for buffer in (disk, memory):
                insert(buffer, i, "human" if i % 3 == 0 else "policy",
                       "offline_demo" if i % 3 == 0 else "online", timeout=i == 8)
        assert disk.pos == memory.pos and disk.full == memory.full
        assert disk.stream_counts() == memory.stream_counts()
        for attr in ("actions", "rewards", "dones", "timeouts", "human_mask", "online_mask"):
            assert np.array_equal(getattr(disk, attr), getattr(memory, attr))
        for values in ("observations", "next_observations"):
            for key in disk.observations:
                assert np.array_equal(getattr(disk, values)[key], getattr(memory, values)[key])
        np.random.seed(23)
        expected = memory.sample(32)
        np.random.seed(23)
        actual = disk.sample(32)
        for key in actual.observations:
            assert np.array_equal(actual.observations[key].numpy(), expected.observations[key].numpy())
        assert np.array_equal(actual.dones.numpy(), expected.dones.numpy())
        assert_consistent(actual)
        demo, online = disk.sample_partition_indices(20)
        assert len(demo) == len(online) == 10
        assert disk.human_mask[demo].all() and disk.online_mask[online].all()
        assert not disk.online_mask[demo].any()
    finally:
        disk.close()


def test_prefetch_is_consistent_during_overwrite_and_batch_resize(tmp_path):
    disk = make_buffer(tmp_path / "replay", capacity=3)
    try:
        insert(disk, 0, "human")
        disk.sample(8)
        def write():
            for i in range(1, 100):
                insert(disk, i, "human")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(write)
            for i in range(60):
                batch = disk.sample(8 if i % 2 else 5)
                assert len(batch.actions) == (8 if i % 2 else 5)
                assert_consistent(batch)
                assert_consistent(disk.sample_human(3))
            future.result()
        assert disk.storage_stats()["prefetch_batches"] == 1
        disk.reset()
        assert disk.size() == 0
        insert(disk, 7)
        assert (disk.sample(8).rewards.numpy() == 7).all()
    finally:
        disk.close()


def test_checkpoint_reopen_preserves_ring_and_can_continue(tmp_path):
    directory = tmp_path / "replay"
    disk = make_buffer(directory)
    for i in range(6):
        insert(disk, i, "human" if i == 4 else "policy", timeout=i == 5)
    counts = disk.stream_counts()
    position = disk.pos
    disk.close()
    restored = DiskHILReplayBuffer.reopen(directory)
    try:
        assert restored.full and restored.pos == position
        assert restored.stream_counts() == counts
        assert_consistent(restored.sample(20))
        insert(restored, 9)
        restored.checkpoint()
        assert json.loads((directory / "manifest.json").read_text())["clean"]
    finally:
        restored.close()


def test_directory_and_writer_protection(tmp_path):
    directory = tmp_path / "replay"
    disk = make_buffer(directory)
    try:
        disk.checkpoint()
        with pytest.raises(FileExistsError):
            make_buffer(directory)
        with pytest.raises(RuntimeError, match="already open"):
            DiskHILReplayBuffer.reopen(directory)
        insert(disk, 1)
        before = disk.observations["state"].copy()
        bad = {"state": np.zeros((1, 5)), "image": np.zeros((1, 8, 8, 3))}
        with pytest.raises(ValueError):
            disk.add(bad, bad, np.zeros((1, 1)), np.zeros(1), np.zeros(1), [{"action_source": "policy"}])
        assert disk.size() == 1 and np.array_equal(before, disk.observations["state"])
    finally:
        disk.close()
    with pytest.raises(RuntimeError, match="closed"):
        disk.sample(1)


def test_uncheckpointed_process_exit_is_rejected(tmp_path):
    directory = tmp_path / "crashed"
    script = '''
import os, sys
import numpy as np
from gymnasium import spaces
from omi_hil_rl.training.disk_replay import DiskHILReplayBuffer
b = DiskHILReplayBuffer(2, spaces.Dict({"state": spaces.Box(-1,1,(1,))}),
                        spaces.Box(-1,1,(1,)), directory=sys.argv[1], device="cpu")
b.checkpoint()
o = {"state": np.zeros((1,1))}
b.add(o,o,np.zeros((1,1)),np.zeros(1),np.zeros(1),[{"action_source":"policy"}])
os._exit(0)
'''
    subprocess.run([sys.executable, "-c", script, str(directory)], check=True)
    with pytest.raises(ValueError, match="clean checkpoint"):
        DiskHILReplayBuffer.reopen(directory)


def test_no_capacity_sized_ram_initialization(tmp_path, monkeypatch):
    from stable_baselines3.common.buffers import DictReplayBuffer
    def forbidden(*args, **kwargs):
        raise AssertionError("must not allocate the in-memory replay first")
    monkeypatch.setattr(DictReplayBuffer, "__init__", forbidden)
    disk = make_buffer(tmp_path / "replay")
    try:
        insert(disk, 2)
        assert_consistent(disk.sample(2))
    finally:
        disk.close()


def test_sac_training_with_disk_replay_and_portable_policy(tmp_path):
    from omi_hil_rl.training.sim_train import train
    from omi_hil_rl.training.executed_action_sac import DemoRegularizedSAC
    from stable_baselines3.common.logger import configure
    metrics = train(
        steps=48, demonstration_steps=24, later_intervention_probability=0.2,
        evaluation_episodes=1, evaluation_interval=24, output_dir=tmp_path / "run",
        seed=0, replay_backend="disk", replay_capacity=16, bc_weight=1,
    )
    assert metrics["sac_updates"] > 0 and metrics["bc_updates"] > 0
    assert metrics["replay_size"] == 16
    assert not (tmp_path / "run/replay.pkl").exists()
    model = DemoRegularizedSAC.load(tmp_path / "run/policy.zip", device="cpu")
    assert model.buffer_size == 1
    replay = DiskHILReplayBuffer.reopen(tmp_path / "run/replay")
    try:
        assert replay.size() == 16
        assert replay.stream_counts() == metrics["replay_streams"]
        model.replay_buffer = replay
        model.set_logger(configure(folder=None, format_strings=[]))
        model.train(gradient_steps=1, batch_size=8)
        assert model._n_updates == metrics["sac_updates"] + 1
    finally:
        replay.close()
