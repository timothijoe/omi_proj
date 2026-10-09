"""Gymnasium real-environment orchestration with manual starts and sparse reward.

Transport owns observation freshness, action arbitration and the physical output.
The environment never calls a vendor SDK. No automatic robot/task reset occurs.
"""
from dataclasses import dataclass, field
import time
import uuid

import gymnasium as gym
import numpy as np

from .config import HILConfig
from omi_hil_rl.training.transition_replay import _spaces


class InteractionUnavailable(RuntimeError):
    """A complete, causally matched interaction could not be acquired."""


class EpisodeTimeout(InteractionUnavailable):
    """Deadline passed between commands; retain/truncate the last valid prefix."""


class EpisodeSuccess(InteractionUnavailable):
    """Success pressed between commands; never send one more motion command."""


class EpisodeManualStop(EpisodeTimeout):
    """Operator ends a human collection episode without claiming success."""


@dataclass
class Interaction:
    observation: dict
    observation_time_ns: int
    action_m_rad: np.ndarray
    source: str
    events: set = field(default_factory=set)
    valid: bool = True
    command_status: str = "simulated"
    event_times: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)


class ButtonEvents:
    """Edges only; startup/reconnect requires release, held buttons never repeat."""
    def __init__(self, config):
        self.codes = dict(start=config.start_button, success=config.success_button,
                          manual_stop=config.stop_button, keep=config.keep_button, discard=config.discard_button)
        self.previous = {key: True for key in self.codes}

    def poll(self, connected, buttons, transitions=()):
        if not connected:
            self.previous = {key: True for key in self.codes}
            return {"disconnect"}
        events = set()
        for code, pressed, initial in transitions:
            for key, expected in self.codes.items():
                if code == expected:
                    if pressed and not initial and not self.previous[key]:
                        events.add(key)
                    self.previous[key] = pressed
        for key, code in self.codes.items():
            pressed = bool(buttons.get(code, False))
            if pressed and not self.previous[key]:
                events.add(key)
            self.previous[key] = pressed
        return events


class RealHILEnv(gym.Env):
    """start -> active -> review; failure/timeouts can be retained by the operator.

    Deadline starts when start is observed, including observation warmup. A success
    event at/after the deadline cannot relabel a timeout. Monotonic wall time is
    separate from the sensor/ROS timestamps used to pair transitions.
    """
    def __init__(self, transport, config=HILConfig(), clock=time.monotonic):
        self.transport, self.config, self.clock = transport, config, clock
        self.observation_space, self.action_space = _spaces(config.replay_contract())
        self.phase = "idle"
        self.previous = None
        self.episode = None
        self.step_number = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if self.phase in ("active", "review"):
            raise RuntimeError("finish/review the current episode before starting another")
        self.transport.stop()
        # Transport waits for an explicit operator start; it never starts at launch.
        start_time = self.transport.wait_start()
        self.started = self.clock() if start_time is None else start_time
        self.deadline = self.started + self.config.episode_seconds
        self.transport.start_episode()
        self.episode = uuid.uuid4().hex
        self.step_number = 0
        try:
            self.previous, self.previous_stamp = self.transport.observe(self.deadline)
            self._check_observation(self.previous)
            if self.clock() >= self.deadline:
                raise InteractionUnavailable("episode timed out while warming observation history")
        except BaseException:
            self.transport.stop()
            self.phase = "idle"
            raise
        self.phase = "active"
        return self.previous, dict(episode=self.episode, started=self.started, deadline=self.deadline)

    def _check_observation(self, observation):
        if not self.observation_space.contains(observation):
            raise InteractionUnavailable("observation shape/dtype/bounds mismatch")
        if not np.all(observation["history_mask"] == 1):
            raise InteractionUnavailable("complete ten-frame causal history is required")
        if self.config.wrist_camera == "required" and not np.all(observation["camera_mask"][:, 1] == 1):
            raise InteractionUnavailable("required wrist camera missing")
        if self.config.wrist_camera == "off" and np.any(observation["camera_mask"][:, 1]):
            raise InteractionUnavailable("wrist camera enabled in an off contract")
        if not np.all(observation["camera_mask"][:, 0] == 1) or np.any(observation["state"][:, :7]):
            raise InteractionUnavailable("external camera required; joint inputs must be disabled")

    def step(self, action):
        if self.phase != "active":
            raise RuntimeError("step requires an explicitly started episode")
        try:
            if self.clock() >= self.deadline:
                raise EpisodeTimeout("deadline passed before command; no fabricated transition")
            physical = self.config.physical_action(action)
            result = self.transport.interact(physical, self.previous_stamp, self.deadline)
            if not result.valid or result.source not in ("human", "policy"):
                raise InteractionUnavailable("missing/stale/paused interaction")
            self._check_observation(result.observation)
            if result.observation_time_ns <= self.previous_stamp:
                raise InteractionUnavailable("next observation must follow the command anchor")
            executed = self.config.normalized_action(result.action_m_rad)
            success_time = result.event_times.get("success", self.clock())
            success = ("success" in result.events and "manual_stop" not in result.events
                       and self.started <= success_time < self.deadline)
            manual_stop = 'manual_stop' in result.events
            timed_out = (self.clock() >= self.deadline or manual_stop) and not success
            cancelled = "disconnect" in result.events or "abort" in result.events
            if cancelled:
                raise InteractionUnavailable("operator disconnected or aborted")
            reward = float(success)
            info = dict(episode=self.episode, step=self.step_number,
                observation_time_ns=self.previous_stamp, next_observation_time_ns=result.observation_time_ns,
                executed_action=executed, action_source=result.source, command_status=result.command_status,
                policy_action=np.asarray(action).copy(), episode_success=success,
                reason="success" if success else "manual_stop" if manual_stop else "timeout" if timed_out else "active",
                valid_transition=True, events=sorted(result.events), event_times=dict(result.event_times),
                command_audit=dict(result.audit))
            self.previous, self.previous_stamp = result.observation, result.observation_time_ns
            self.step_number += 1
            if success or timed_out:
                self.transport.stop()
                self.phase = "review"
            return self.previous, reward, success, timed_out, info
        except BaseException:
            self.transport.stop()
            self.phase = "review"
            raise

    def review(self):
        if self.phase != "review":
            raise RuntimeError("review requires an ended episode")
        self.transport.stop()
        self.transport.reset_requires_release = True
        keep = self.config.review == "auto" or self.transport.wait_review()
        self.phase = "idle"
        return bool(keep)

    def close(self):
        try:
            self.transport.stop()
        finally:
            self.transport.close()
            self.phase = "closed"


class FakeTransport:
    """Explicit synthetic transport for software validation, never a real robot."""
    def __init__(self, config=HILConfig(), *, success_step=5, clock=None):
        self.config, self.success_step = config, success_step
        self.steps = 0
        self.stamp = 1_000_000_000
        self.state = np.zeros(14, np.float32)
        self.stops = 0

    def wait_start(self):
        pass

    def reset_history(self):
        self.steps = 0
        self.state[:] = 0

    def start_episode(self):
        # Synthetic transports reset their fixture state rather than sensor data.
        self.reset_history()

    def _observation(self):
        return dict(rgb=np.zeros((10, 3, 128, 128), np.uint8),
            wrist_rgb=np.zeros((10, 3, 128, 128), np.uint8),
            tactile=np.zeros((10, 10, 16, 24), np.float32),
            state=np.tile(self.state, (10, 1)), camera_mask=np.tile(np.array([1., 0.], np.float32), (10, 1)),
            history_mask=np.ones(10, np.uint8))

    def observe(self, deadline):
        self.stamp += 100_000_000
        return self._observation(), self.stamp

    def interact(self, action, anchor_stamp, deadline):
        self.steps += 1
        self.state[7:10] += action[:3]
        self.stamp += 100_000_000
        return Interaction(self._observation(), self.stamp, action.copy(), "policy",
                           {"success"} if self.steps == self.success_step else set())

    def wait_review(self):
        return True

    def stop(self):
        self.stops += 1

    def close(self):
        pass
