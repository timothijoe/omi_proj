"""Reward-independent demo capture, causal command labels and episode-held-out BC."""
from dataclasses import replace
import copy
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.demo import collect, annotate, read_demo_step, validate_command_label, SyntheticHuman
from omi_hil_rl.training.demo_bc import make_plan, DemoDataset, statistics, train, metrics
from omi_hil_rl.hil.networks import load_actor
from omi_hil_rl.real.sdk_action import output_action


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def test_capture_keeps_observations_and_adopted_command_without_reward(tmp_path):
    manifests = collect(tmp_path / "capture", HILConfig(), episodes=3, fake_steps=3)
    assert len(manifests) == 3 and all(m["keep"] and m["synthetic"] for m in manifests)
    for manifest in manifests:
        directory = tmp_path / "capture" / "episodes" / manifest["episode"]
        obs, nxt, action, metadata = read_demo_step(directory, 0)
        assert set(obs) == set(nxt) == {"rgb", "wrist_rgb", "tactile", "state", "camera_mask", "history_mask"}
        assert np.any(action) and metadata["action_source"] == "human"
        assert "reward" not in metadata and not manifest["reward_available"]
        assert metadata["observation_time_ns"] < metadata["next_observation_time_ns"]
        assert not (directory / "ready.json").exists()  # never auto-import unlabelled collection into RL
    assert len((tmp_path / "capture" / "events.jsonl").read_text().splitlines()) > 9


def test_reward_sidecars_never_change_source_or_bc_labels(tmp_path):
    manifests = collect(tmp_path / "capture", HILConfig(), episodes=2, fake_steps=3)
    directory = tmp_path / "capture" / "episodes" / manifests[0]["episode"]
    original = (directory / "000000.npz").read_bytes()
    first = annotate(directory, outcome="success", version="manual_v1", success_step=1)
    assert first["rewards"] == [0., 1.] and first["valid_length"] == 2
    second = annotate(directory, outcome="timeout", version="manual_v2")
    assert second["truncated"] == [False, False, True] and second["rewards"] == [0., 0., 0.]
    assert (directory / "000000.npz").read_bytes() == original
    with pytest.raises(FileExistsError):
        annotate(directory, outcome="failure", version="manual_v1")
    with pytest.raises(ValueError, match="outside"):
        annotate(directory, outcome="success", version="bad", success_step=100)
    plan = make_plan([tmp_path / "capture"], tmp_path / "plan.json")
    assert len(DemoDataset(plan, "training")) == 3


def test_rejected_or_discarded_episodes_are_not_training_data(tmp_path):
    class Discard(SyntheticHuman):
        def wait_review(self):
            return False
    result = collect(tmp_path / "discard", HILConfig(), episodes=1, transport=Discard(HILConfig(), success_step=2))
    assert not result[0]["keep"]
    with pytest.raises(ValueError, match="distinct validation"):
        make_plan([tmp_path / "discard"], tmp_path / "plan.json")


def test_bc_episode_split_train_only_statistics_and_hash_guard(tmp_path):
    collect(tmp_path / "capture", HILConfig(), episodes=4, fake_steps=2)
    plan = make_plan([tmp_path / "capture"], tmp_path / "plan.json", validation_episodes=1)
    assert not {x["episode"] for x in plan["training"]} & {x["episode"] for x in plan["validation"]}
    dataset = DemoDataset(plan, "training")
    norm, mean = statistics(dataset)
    assert mean.shape == (6,) and np.isfinite(mean).all()
    np.testing.assert_array_equal(np.asarray(norm["state_mean"])[0, :7], np.zeros(7))
    np.testing.assert_array_equal(np.asarray(norm["state_std"])[0, :7], np.ones(7))
    leaked = copy.deepcopy(plan)
    leaked["validation"] = leaked["training"][:1]
    with pytest.raises(ValueError, match="leakage"):
        DemoDataset(leaked, "training")
    sample = Path(plan["training"][0]["path"]) / "000000.npz"
    sample.write_bytes(sample.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        DemoDataset(plan, "training")


def command_metadata():
    config = HILConfig(transport="ros")
    action = np.full(6, .3, np.float32)
    physical = config.physical_action(action)
    wire = output_action(physical, config.sdk_convention)
    receipt = dict(command_id="hil:test", accepted=True, finished=True, wire_action=wire)
    trace = dict(command_id="hil:test", command_topic="/omi/action/decision", observation_reference_ns=100,
        command_send_ns=110, action_source="human", label_candidate=True, action_m_rad=physical.tolist(),
        normalized_action=action.tolist(), action_contract=config.replay_contract()["action_contract"],
        wire_action=wire, output_convention=config.sdk_convention)
    metadata = dict(observation_time_ns=100, next_observation_time_ns=200,
        command_audit=dict(command_id="hil:test", command_topic="/omi/action/decision", command_send_ns=111,
                           command_trace=trace, receipt=receipt, wire_action=wire))
    return config, action, metadata


def test_causal_label_matches_sent_wire_units_axes_and_receipt():
    config, action, metadata = command_metadata()
    validate_command_label(config.replay_contract(), action, metadata)
    bad = copy.deepcopy(metadata)
    bad["command_audit"]["command_trace"]["wire_action"][0] += 1
    with pytest.raises(ValueError, match="wire command"):
        validate_command_label(config.replay_contract(), action, bad)
    bad = copy.deepcopy(metadata)
    bad["command_audit"]["receipt"]["accepted"] = False
    with pytest.raises(ValueError, match="not adopted"):
        validate_command_label(config.replay_contract(), action, bad)
    bad = copy.deepcopy(metadata)
    bad["observation_time_ns"] = 120
    with pytest.raises(ValueError, match="anchor|noncausal"):
        validate_command_label(config.replay_contract(), action, bad)
    bad = copy.deepcopy(metadata)
    bad["command_audit"]["receipt"]["command_id"] = "different"
    with pytest.raises(ValueError, match="ID mismatch"):
        validate_command_label(config.replay_contract(), action, bad)


def test_periodic_bc_label_requires_causal_acceptance_and_eef():
    from omi_hil_rl.hil.periodic_bc_label import validate_bc_label
    config, action, old = command_metadata()
    trace = old['command_audit']['command_trace']
    trace.update(observation_reference_ns=1_000_000_000,
                 command_send_ns=1_030_000_000, execution_confirmed=False)
    receipt = dict(old['command_audit']['receipt'], status='queue_accepted',
                   timestamp_ns=1_031_000_000, arm='A', delta_frame='base',
                   control_mode='velocity_hold', action_source='human', nominal_duration_s=.1)
    metadata = dict(episode='source-segment-000010', action_source='human',
        command_status='periodic_accepted_command', observation_time_ns=1_000_000_000,
        next_observation_time_ns=1_100_000_000,
        command_audit=dict(source_episode='source', periodic_tick=10, command_id='hil:test',
                           command_trace=trace, receipts=[receipt],
                           next_eef_receive_ns=1_080_000_000,
                           semantics='accepted_command_not_measured_displacement'))
    with pytest.raises(ValueError, match='missing command label'):
        validate_command_label(config.replay_contract(), action, metadata)
    validate_bc_label(config.replay_contract(), action, metadata)
    bad = copy.deepcopy(metadata)
    bad['command_audit']['receipts'][0]['accepted'] = False
    with pytest.raises(ValueError, match='acceptance'):
        validate_bc_label(config.replay_contract(), action, bad)
    bad = copy.deepcopy(metadata)
    bad['command_audit']['next_eef_receive_ns'] = 1_030_000_000
    with pytest.raises(ValueError, match='causal'):
        validate_bc_label(config.replay_contract(), action, bad)


def test_bc_training_and_evaluation_do_not_need_reward(tmp_path):
    collect(tmp_path / "capture", HILConfig(), episodes=4, fake_steps=3)
    plan_path = tmp_path / "plan.json"
    plan = make_plan([tmp_path / "capture"], plan_path)
    report = train(plan_path, tmp_path / "bc", steps=20, batch_size=4, evaluate_every=10)
    assert not report["reward_used"] and report["synthetic"]
    assert report["best_validation"]["normalized_mse"] < report["history"][0]["validation"]["normalized_mse"]
    assert report["checkpoint_reload_match"]
    assert "validation_train_mean_baseline" in report
    actor, _, _ = load_actor(tmp_path / "bc" / "actor.pt", plan["contract"])
    measured = metrics(actor, DemoDataset(plan, "validation"))
    assert measured["normalized_mse"] == pytest.approx(report["best_validation"]["normalized_mse"])
    assert not (tmp_path / "bc" / "learner.pt").exists()


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_multimodal_bc_updates_control_head_and_keeps_backbone(tmp_path, device):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    from omi_hil_rl.hil.networks import Actor
    from omi_hil_rl.training.eef_bc_grid import GridProfile
    weights = Path(__file__).resolve().parents[1] / "local/pretrained/serl_resnet10/backbone.pt"
    if not weights.exists():
        pytest.skip("official backbone artifact unavailable")
    collect(tmp_path / "capture", HILConfig(), episodes=2, fake_steps=2)
    plan = make_plan([tmp_path / "capture"], tmp_path / "plan.json")
    dataset = DemoDataset(plan, "training")
    norm, _ = statistics(dataset)
    actor = Actor(dict(encoder="current9stack", base_contract=GridProfile().CONTRACT, normalization=norm)).to(device).eval()
    actor.encoder.initialize_pretrained(torch.load(weights, map_location="cpu", weights_only=True))
    before = {key:value.clone() for key,value in actor.encoder.model.backbone.state_dict().items()}
    head = actor.head[-1].weight.detach().clone()
    stem = actor.encoder.model.history_stem.weight.detach().clone()
    obs, action = dataset[0]
    obs = {key:torch.as_tensor(value, device=device)[None] for key,value in obs.items()}
    target = torch.as_tensor(action, device=device)[None]
    optimizer = torch.optim.Adam([p for p in actor.parameters() if p.requires_grad], lr=1e-3)
    for _ in range(2):
        predicted = actor.sample(obs, deterministic=True)[0]
        loss = (predicted - target).square().mean()
        assert torch.isfinite(loss)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    assert not torch.equal(head, actor.head[-1].weight)
    assert not torch.equal(stem, actor.encoder.model.history_stem.weight)
    assert all(torch.equal(value,before[key]) for key,value in actor.encoder.model.backbone.state_dict().items())


def test_between_episode_manual_reset_is_not_a_training_label():
    from types import SimpleNamespace
    from omi_hil_rl.hil.ros_transport import RosTransport
    from omi_hil_rl.real.gamepad_control import Mapping, BTN_TR, ABS_RY
    transport = RosTransport.__new__(RosTransport)
    transport.allow_manual_reset = True
    transport.publisher = object()
    transport.config = HILConfig()
    transport.mapping = Mapping()
    transport.connected = True
    transport.pad = SimpleNamespace(buttons={BTN_TR: True}, axes={ABS_RY: -1.})
    published, stopped = [], []
    transport._publish = lambda action, command_id=None: published.append((action, command_id))
    transport.stop = lambda: stopped.append(True)
    transport._manual_reset_tick()
    transport._manual_reset_tick()
    assert len(published) == 1 and published[0][0][0] > 0
    assert published[0][1] is None
    transport.pad.buttons[BTN_TR] = False
    transport._manual_reset_tick()
    assert stopped == [True]
