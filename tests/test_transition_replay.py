import copy
import json
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip("stable_baselines3")
from omi_hil_rl.training.transition_replay import TransitionReplay


def contract():
    return dict(schema_version=1, observation_contract="test-camera-state-v1",
                action_contract="test-eef-base-m-rotvec-rad-v1", reward_contract="test-binary-v1",
                action_semantics="accepted_command", observations={
                    "rgb": dict(shape=[3, 4, 4], dtype="uint8", low=0, high=255),
                    "state": dict(shape=[2], dtype="float32", low=-100, high=100),
                }, action=dict(shape=[6], dtype="float32", low=-1, high=1))


def record(step=0, source="human", success=True):
    return dict(**{k: v for k, v in contract().items() if k.endswith("contract") or k == "action_semantics"},
                episode="episode-1", step=step, observation_time_ns=1000 + step * 100,
                next_observation_time_ns=1100 + step * 100,
                observation={"state": [step, step], "rgb": np.full((3, 4, 4), step).tolist()},
                next_observation={"state": [step + 1, step + 1], "rgb": np.full((3, 4, 4), step + 1).tolist()},
                executed_action=[0.1] * 6, action_source=source, reward=0.0,
                terminated=False, truncated=False, episode_success=success)


def test_routing_disk_sampling_and_reopen(tmp_path):
    directory = tmp_path / "replay"
    with TransitionReplay(directory, contract(), 8) as replay:
        replay.append(record(), origin="offline_demo")
        replay.append(record(1, "policy"))
        replay.append(record(2, "human", False))
        assert replay.report()["streams"] == dict(online=2, demonstration=2, offline_demonstration=1)
        assert isinstance(replay.buffer.observations["rgb"], np.memmap)
        demo, online = replay.buffer.sample_partition_indices(64)
        assert len(demo) == len(online) == 32
        assert set(online) <= {1, 2} and set(demo) <= {0, 2}
        assert replay.buffer.sample(64).actions.shape == (64, 6)
        assert replay.metadata(0)["replay_origin"] == "offline_demo"
    with TransitionReplay.reopen(directory, expected_contract=contract()) as replay:
        assert replay.metadata(2)["action_source"] == "human"
        assert replay.metadata(2)["step"] == 2
        assert replay.metadata(2)["next_observation_time_ns"] == 1300
        assert replay.buffer.observations["rgb"].dtype == np.uint8
        replay.append(record(3, "policy"))
        assert replay.buffer.size() == 4
    changed = contract()
    changed["reward_contract"] = "another-reward"
    with pytest.raises(ValueError, match="contract mismatch"):
        TransitionReplay.reopen(directory, expected_contract=changed)


@pytest.mark.parametrize("change", [
    {"action_semantics": "future_recorded_eef_change_proxy_not_control_command"},
    {"action_contract": "sdk-mm-abc-deg"},
    {"reward": None},
    {"next_observation": None},
    {"executed_action": [0.0] * 7},
    {"executed_action": [float("nan")] * 6},
    {"next_observation_time_ns": 999},
    {"action_source": "paused"},
    {"terminated": 1},
])
def test_incomplete_or_incompatible_record_does_not_mutate(tmp_path, change):
    with TransitionReplay(tmp_path / "replay", contract(), 4) as replay:
        replay.append(record())
        bad = record(1)
        bad.update(change)
        with pytest.raises(ValueError):
            replay.append(bad)
        assert replay.buffer.size() == 1 and replay.buffer.pos == 1
        assert replay.metadata(0)["step"] == 0


def test_initial_demo_requires_confirmed_success_and_human_source(tmp_path):
    with TransitionReplay(tmp_path / "replay", contract(), 4) as replay:
        for value in (record(source="policy"), record(success=False)):
            with pytest.raises(ValueError, match="confirmed"):
                replay.append(value, origin="offline_demo")
        # Failure during online interaction never removes human corrections.
        replay.append(record(success=False), origin="online")
        assert replay.buffer.stream_counts() == dict(online=1, demonstration=1, offline_demonstration=0)


def test_pixels_do_not_wrap_or_truncate_and_metadata_follows_ring(tmp_path):
    with TransitionReplay(tmp_path / "replay", contract(), 2) as replay:
        for pixel in (256, -1, 1.5):
            bad = record()
            bad["observation"]["rgb"][0][0][0] = pixel
            with pytest.raises(ValueError):
                replay.append(bad)
        for i in range(3):
            replay.append(record(i, "policy"))
        assert replay.buffer.size() == 2
        assert replay.metadata(0)["step"] == 2
        assert replay.metadata(1)["step"] == 1
        assert replay.buffer.observations["state"][0, 0, 0] == 2


def test_streaming_import_and_cli_append(tmp_path):
    schema = tmp_path / "contract.json"
    schema.write_text(json.dumps(contract()))
    demos = tmp_path / "demos.jsonl"
    demos.write_text(json.dumps(record()) + "\n")
    directory = tmp_path / "replay"
    base = [sys.executable, "-m", "omi_hil_rl.training.transition_replay"]
    created = subprocess.run(base + ["create", "--directory", str(directory), "--contract", str(schema),
                             "--capacity", "8", "--offline-demo", str(demos)], capture_output=True, text=True, check=True)
    assert json.loads(created.stdout)["streams"]["offline_demonstration"] == 1
    online = tmp_path / "online.jsonl"
    online.write_text(json.dumps(record(1, "policy")) + "\n" + json.dumps(record(2)) + "\n")
    appended = subprocess.run(base + ["append", "--directory", str(directory), "--online", str(online)],
                              capture_output=True, text=True, check=True)
    assert json.loads(appended.stdout)["streams"] == dict(online=2, demonstration=2, offline_demonstration=1)
    inspected = subprocess.run(base + ["inspect", "--directory", str(directory)], capture_output=True, text=True, check=True)
    assert json.loads(inspected.stdout)["size"] == 3
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(record(3)) + "\n{}\n")
    with TransitionReplay.reopen(directory) as replay:
        with pytest.raises(ValueError, match="2:.*1 earlier rows accepted"):
            replay.import_jsonl(bad, origin="online")
        assert replay.buffer.size() == 4


def test_proxy_contract_rejected_before_creating_directory(tmp_path):
    value = copy.deepcopy(contract())
    value["action_semantics"] = "future-state-proxy"
    with pytest.raises(ValueError, match="proxy"):
        TransitionReplay(tmp_path / "replay", value, 8)
    assert not (tmp_path / "replay").exists()
