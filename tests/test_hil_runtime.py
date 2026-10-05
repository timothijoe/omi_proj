"""HIL lifecycle, replay handoff and actual gradient updates without hardware."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import ButtonEvents, FakeTransport, RealHILEnv, InteractionUnavailable
from omi_hil_rl.hil.exchange import EpisodeSpool, import_ready, publish, owner_lock
from omi_hil_rl.hil.networks import SAC, load_actor
from omi_hil_rl.training.transition_replay import TransitionReplay


@pytest.fixture(autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def test_button_edges_and_reconnect_require_release():
    config = HILConfig()
    events = ButtonEvents(config)
    held = {config.start_button: True}
    assert events.poll(True, held) == set()
    assert events.poll(True, {}) == set()
    assert events.poll(True, held) == {"start"}
    assert events.poll(True, held) == set()
    assert events.poll(False, {}) == {"disconnect"}
    assert events.poll(True, held) == set()
    events.poll(True, {})
    assert events.poll(True, held) == {"start"}


def collect(run, config=HILConfig(), *, origin="online", human=False, keep=True, timeout=False):
    clock = [100.]
    class Transport(FakeTransport):
        def wait_start(self):
            clock[0] = 200.
        def interact(self, *args):
            result = super().interact(*args)
            if human:
                result.source = "human"
                result.action_m_rad = config.physical_action(np.full(6, .25, np.float32))
            if timeout:
                clock[0] = 216.
            return result
        def wait_review(self):
            return keep
    transport = Transport(config, success_step=1)
    env = RealHILEnv(transport, config, clock=lambda: clock[0])
    observation, reset_info = env.reset()
    assert reset_info["started"] == 200. and reset_info["deadline"] == 215.
    spool = EpisodeSpool(run, reset_info["episode"], config.replay_contract(), origin=origin)
    nxt, reward, terminated, truncated, info = env.step(np.zeros(6, np.float32))
    spool.append(observation, nxt, reward, terminated, truncated, info)
    manifest = spool.finish(env.review())
    env.close()
    return manifest, info


def test_success_timeout_review_and_executed_human_action(tmp_path):
    manifest, info = collect(tmp_path, human=True)
    assert manifest["keep"] and manifest["episode_success"]
    np.testing.assert_array_equal(info["executed_action"], np.full(6, .25, np.float32))
    timeout, timeout_info = collect(tmp_path, timeout=True)
    assert timeout["keep"] and not timeout["episode_success"]
    assert timeout_info["reason"] == "timeout"
    discarded, _ = collect(tmp_path, keep=False)
    assert not discarded["keep"]
    assert not (tmp_path / "episodes" / discarded["episode"] / "ready.json").exists()


def test_missing_or_stale_feedback_cannot_create_transition():
    config = HILConfig()
    transport = FakeTransport(config)
    env = RealHILEnv(transport)
    with pytest.raises(RuntimeError, match="explicitly started"):
        env.step(np.zeros(6))
    env.reset()
    original = transport.interact
    def stale(*args):
        result = original(*args)
        result.observation_time_ns = args[1]
        return result
    transport.interact = stale
    with pytest.raises(InteractionUnavailable, match="follow"):
        env.step(np.zeros(6))
    assert env.phase == "review" and transport.stops >= 2


def test_handoff_routing_idempotence_and_timeout_bootstrap(tmp_path):
    config = HILConfig()
    collect(tmp_path, origin="offline_demo", human=True)
    collect(tmp_path, human=True, timeout=True)
    collect(tmp_path)
    collect(tmp_path, keep=False)
    replay = TransitionReplay(tmp_path / "replay", config.replay_contract(), 8, prefetch=False)
    try:
        assert import_ready(tmp_path, replay) == 3
        assert replay.buffer.stream_counts() == dict(online=2, demonstration=2, offline_demonstration=1)
        assert import_ready(tmp_path, replay) == 0
        truncated_ids = [i for i in range(3) if replay.buffer.timeouts[i, 0]]
        assert len(truncated_ids) == 1
        batch = replay.buffer._get_samples(np.array(truncated_ids))
        assert batch.dones.item() == 0 and batch.rewards.item() == 0
        success_ids = [i for i in range(3) if not replay.buffer.timeouts[i, 0]]
        assert replay.buffer._get_samples(np.array(success_ids)).dones.sum() == 2
    finally:
        replay.close()
    with TransitionReplay.reopen(tmp_path / "replay", prefetch=False) as reopened:
        assert reopened.buffer.size() == 3


def test_offline_demo_policy_rejected_and_incomplete_never_published(tmp_path):
    with pytest.raises(ValueError, match="policy actions"):
        collect(tmp_path, origin="offline_demo")
    spool = EpisodeSpool(tmp_path, "incomplete", HILConfig().replay_contract())
    with pytest.raises(ValueError, match="incomplete"):
        spool.finish(True)
    assert not (spool.directory / "ready.json").exists()
    spool.finish(False)


def test_single_writer_lock(tmp_path):
    with owner_lock(tmp_path, "learner"):
        with pytest.raises(RuntimeError, match="another learner"):
            with owner_lock(tmp_path, "learner"):
                pass
        with owner_lock(tmp_path, "actor"):
            pass


def make_batch(observation, batch_size=2):
    obs = {k: torch.as_tensor(np.stack([v] * batch_size)) for k, v in observation.items()}
    return SimpleNamespace(observations=obs, next_observations=obs,
        actions=torch.full((batch_size, 6), .25), rewards=torch.ones(batch_size, 1), dones=torch.zeros(batch_size, 1))


def test_sac_gradients_ratio_checkpoint_and_contract(tmp_path):
    torch.manual_seed(3)
    config = HILConfig()
    agent = SAC(dict(encoder="synthetic-test"), config.replay_contract())
    obs = FakeTransport()._observation()
    before_actor = [v.detach().clone() for v in agent.actor.parameters()]
    before_critic = [v.detach().clone() for v in agent.critic.parameters()]
    first = agent.update(make_batch(obs))
    assert "actor_loss" not in first
    assert all(torch.equal(a, b) for a, b in zip(before_actor, agent.actor.parameters()))
    assert any(not torch.equal(a, b) for a, b in zip(before_critic, agent.critic.parameters()))
    second = agent.update(make_batch(obs))
    assert all(np.isfinite(value) for value in second.values())
    assert any(not torch.equal(a, b) for a, b in zip(before_actor, agent.actor.parameters()))
    action = agent.act(obs, deterministic=True)
    assert action.shape == (6,) and np.max(np.abs(action)) <= 1
    checkpoint = agent.checkpoint()
    expected_random = np.random.random()
    restored = SAC.restore(checkpoint, expected_contract=config.replay_contract())
    assert np.random.random() == expected_random
    np.testing.assert_array_equal(restored.act(obs, True), action)
    assert restored.updates == 2
    publish(tmp_path, agent)
    actor, version, _ = load_actor(tmp_path / "actor.pt", config.replay_contract())
    assert version == 2
    with torch.inference_mode():
        np.testing.assert_array_equal(actor.sample(agent.observation(obs, single=True), True)[0][0].numpy(), action)
    with pytest.raises(ValueError, match="mismatch"):
        load_actor(tmp_path / "actor.pt", replace(config, episode_seconds=20).replay_contract())
    with pytest.raises(ValueError, match="forbidden"):
        SAC(dict(encoder="synthetic-test"), replace(config, transport="ros").replay_contract())


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_multimodal_encoder_frozen_backbone_and_trainable_history(device):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable in this interpreter")
    from omi_hil_rl.training.eef_bc_grid import GridProfile
    weights_path = Path(__file__).resolve().parents[1] / "local/pretrained/serl_resnet10/backbone.pt"
    if not weights_path.exists():
        pytest.skip("local pretrained artifact unavailable")
    norm = dict(tactile_mean=np.zeros((1, 10, 1, 1)).tolist(), tactile_std=np.ones((1, 10, 1, 1)).tolist(),
                state_mean=np.zeros((1, 14)).tolist(), state_std=np.ones((1, 14)).tolist())
    recipe = dict(encoder="current9stack", base_contract=GridProfile().CONTRACT, normalization=norm)
    agent = SAC(recipe, HILConfig().replay_contract(), device=device, pretrained=torch.load(weights_path, weights_only=True))
    obs = FakeTransport()._observation()
    obs["rgb"][:] = 100
    before = {k: v.clone() for k, v in agent.critic.encoder.model.backbone.state_dict().items()}
    stem = agent.critic.encoder.model.history_stem.weight.detach().clone()
    batch = make_batch(obs, 1)
    agent.update(batch)
    agent.update(batch)
    assert all(torch.equal(value, before[key]) for key, value in agent.critic.encoder.model.backbone.state_dict().items())
    assert not torch.equal(stem, agent.critic.encoder.model.history_stem.weight)
    assert agent.act(obs).shape == (6,)
    assert np.isfinite(agent.act(obs)).all()
    restored = SAC.restore(agent.checkpoint(), device=device, expected_contract=HILConfig().replay_contract())
    np.testing.assert_allclose(restored.act(obs, True), agent.act(obs, True), atol=1e-7)


def test_actor_learner_in_separate_processes(tmp_path):
    run = tmp_path / "run"
    command = [sys.executable, "-m", "omi_hil_rl.hil.learner", "--run", str(run), "--capacity", "16",
               "--batch-size", "2", "--min-demo", "0", "--updates", "4", "--wait-seconds", "35", "--threads", "1"]
    with (tmp_path / "learner.log").open("w") as log:
        learner = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            actor = subprocess.run([sys.executable, "-m", "omi_hil_rl.hil.actor", "--run", str(run), "--episodes", "2",
                                    "--threads", "1"], capture_output=True, text=True, timeout=40)
            assert actor.returncode == 0, actor.stderr
            assert learner.wait(timeout=40) == 0, (tmp_path / "learner.log").read_text()
        finally:
            if learner.poll() is None:
                learner.terminate()
                learner.wait(timeout=5)
    checkpoint = torch.load(run / "learner.pt", weights_only=True)
    assert checkpoint["updates"] == 4
    # Actor can finish its next episode after learner exits; retained handoff remains durable.
    with TransitionReplay.reopen(run / "replay", prefetch=False) as replay:
        import_ready(run, replay)
        assert replay.buffer.stream_counts()["online"] == 10
    assert len(list((run / "episodes").glob("*/ready.json"))) == 2


def test_success_pressed_before_deadline_survives_feedback_latency():
    clock = [0.]
    class LateFeedback(FakeTransport):
        def interact(self, *args):
            result = super().interact(*args)
            result.events = {"success"}
            result.event_times = {"success": 14.9}
            clock[0] = 15.05
            return result
    env = RealHILEnv(LateFeedback(), clock=lambda: clock[0])
    env.reset()
    _, reward, terminated, truncated, _ = env.step(np.zeros(6))
    assert reward == 1 and terminated and not truncated


def test_invalid_retained_episode_is_checked_before_replay_mutation(tmp_path):
    manifest, _ = collect(tmp_path)
    path = tmp_path / "episodes" / manifest["episode"] / "000000.npz"
    with np.load(path, allow_pickle=False) as archive:
        arrays = {k: archive[k] for k in archive.files}
    arrays["executed_action"] = np.full(6, 2., np.float32)
    np.savez_compressed(path, **arrays)
    with TransitionReplay(tmp_path / "replay", HILConfig().replay_contract(), 8, prefetch=False) as replay:
        with pytest.raises(ValueError, match="outside configured bounds"):
            import_ready(tmp_path, replay)
        assert replay.buffer.size() == 0
        assert not (tmp_path / "import_pending.json").exists()


def test_clean_checkpoint_receipt_interruption_does_not_duplicate(tmp_path):
    manifest, _ = collect(tmp_path)
    directory = tmp_path / "episodes" / manifest["episode"]
    with TransitionReplay(tmp_path / "replay", HILConfig().replay_contract(), 8, prefetch=False) as replay:
        import_ready(tmp_path, replay)
    receipt = json.loads((directory / "imported.json").read_text())
    (directory / "imported.json").unlink()
    (tmp_path / "import_pending.json").write_text(json.dumps(receipt))
    with TransitionReplay.reopen(tmp_path / "replay", prefetch=False) as replay:
        assert import_ready(tmp_path, replay) == 0
        assert replay.buffer.size() == 1
        assert (directory / "imported.json").exists()


@pytest.mark.parametrize("rejected,stale_eef", [(False, False), (True, False), (False, True)])
def test_ros_transport_requires_matching_receipt_and_post_command_eef(monkeypatch, rejected, stale_eef):
    from omi_hil_rl.hil.ros_transport import RosTransport
    from omi_hil_rl.real.gamepad_control import Mapping
    transport = RosTransport.__new__(RosTransport)
    clock = [10.]
    stamp = [1_100_000_000]
    monkeypatch.setattr("omi_hil_rl.hil.ros_transport.time.monotonic", lambda: clock[0])
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=stamp[0])))
    transport.pad = SimpleNamespace(buttons={}, axes={})
    transport.mapping = Mapping()
    transport.events, transport.event_times, transport.receipts = set(), {}, {}
    transport.connected, transport.human_only, transport.last_owner = True, False, None
    transport.latest = None
    sent = []
    def publish_action(action, command_id=None):
        sent.append(action.copy())
        wire = action.tolist()
        transport.receipts[command_id] = dict(accepted=not rejected, delta_frame="base", arm="A", wire_action=wire,
                                                finished=True, status="sdk_commands_sent")
        return wire
    transport._publish = publish_action
    transport.stop = lambda: None
    def pump():
        clock[0] += .01
        stamp[0] += 10_000_000
        if sent:
            transport.latest = (FakeTransport()._observation(), stamp[0])
            transport.latest_eef_time = 1 if stale_eef else stamp[0]
    transport._pump = pump
    if rejected or stale_eef:
        with pytest.raises(InteractionUnavailable, match="rejected|missing"):
            transport.interact(np.zeros(6, np.float32), 1_100_000_000, 11.)
    else:
        interaction = transport.interact(np.zeros(6, np.float32), 1_100_000_000, 11.)
        assert interaction.command_status == "sdk_commands_sent_not_execution_confirmed"
        assert interaction.source == "policy"
    assert len(sent) == 1


def test_deadline_between_commands_retains_valid_prefix_without_new_action(tmp_path):
    from omi_hil_rl.hil.environment import EpisodeTimeout
    clock = [0.]
    env = RealHILEnv(FakeTransport(success_step=100), clock=lambda: clock[0])
    obs, info = env.reset()
    spool = EpisodeSpool(tmp_path, info["episode"], HILConfig().replay_contract())
    nxt, reward, terminated, truncated, step_info = env.step(np.zeros(6))
    spool.append(obs, nxt, reward, terminated, truncated, step_info)
    clock[0] = 15.
    with pytest.raises(EpisodeTimeout):
        env.step(np.zeros(6))
    assert env.transport.steps == 1
    spool.truncate_valid_prefix()
    assert env.review()
    manifest = spool.finish(True, reason="timeout_between_commands")
    assert manifest["count"] == 1 and not manifest["episode_success"]
    with TransitionReplay(tmp_path / "replay", HILConfig().replay_contract(), 8, prefetch=False) as replay:
        assert import_ready(tmp_path, replay) == 1
        assert replay.buffer.timeouts[0, 0]
        assert replay.buffer._get_samples(np.array([0])).dones.item() == 0
