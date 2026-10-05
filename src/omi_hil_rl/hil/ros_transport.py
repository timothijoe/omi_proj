"""ROS observation collector and tagged final-command transport, lazy ROS imports."""
import json
import time
import uuid

import numpy as np

from .environment import ButtonEvents, Interaction, InteractionUnavailable, EpisodeTimeout, EpisodeSuccess, EpisodeManualStop
from omi_hil_rl.real.gamepad_control import Mapping, BTN_TR, wire_action
from omi_hil_rl.real.linux_gamepad import LinuxGamepad
from omi_hil_rl.training.stack_shadow import StackObservations


class RosTransport:
    def __init__(self, config, base_contract, *, execute=False, gamepad="/dev/input/js0",
                 topic="/omi/action/decision", convention="sdk-x-forward-z-left", rgb_max_age_ms=None):
        if config.transport != "ros":
            raise ValueError("ROS transport requires a ROS replay contract")
        if convention not in ("sdk-base-aligned", "sdk-x-forward-z-left"):
            raise ValueError("HIL requires an explicit SDK ABC conversion")
        import rclpy
        from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        from geometry_msgs.msg import PoseStamped
        from std_msgs.msg import Float64MultiArray, String
        self.rclpy = rclpy
        self.owns_context = not rclpy.ok()
        if self.owns_context:
            rclpy.init()
        self.node = rclpy.create_node("omi_hil_actor", enable_rosout=False)
        self.config, self.topic, self.convention = config, topic, convention
        self.runtime = StackObservations(base_contract, "strict", config.eef_reference,
                                         rgb_max_age_ms=rgb_max_age_ms)
        self.pad, self.buttons = LinuxGamepad(gamepad), ButtonEvents(config)
        self.mapping = Mapping(hz=config.hz, translation_m_s=config.translation_step_m * config.hz,
                               rotation_rad_s=config.rotation_step_rad * config.hz)
        self.publisher = self.node.create_publisher(Float64MultiArray, topic,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)) if execute else None
        self.trace_publisher = self.node.create_publisher(String, "/omi/action/command_trace", 10) if execute else None
        self.receipts = {}
        for topic_name, key in self.runtime.topics.items():
            self.node.create_subscription(PoseStamped if key == "eef" else Image, topic_name,
                lambda msg, k=key: self.runtime.ingest(k, msg, self.node.get_clock().now().nanoseconds), qos_profile_sensor_data)
        self.node.create_subscription(String, "/omi/action/receipt", self._receipt, 10)
        self.next_reference = None
        self.latest = None
        self.events = set()
        self.event_times = {}
        self.connected = False
        self.last_owner = None
        self.human_only = False

    def _receipt(self, message):
        try:
            receipt = json.loads(message.data)
            self.receipts[receipt["command_id"]] = receipt
            if len(self.receipts) > 64:
                self.receipts.pop(next(iter(self.receipts)))
        except (ValueError, KeyError, TypeError):
            pass

    def _pump(self):
        if not self.rclpy.ok():
            raise InteractionUnavailable("ROS shutdown")
        health_check = getattr(self, "health_check", None)
        if health_check:
            health_check()
        self.rclpy.spin_once(self.node, timeout_sec=.005)
        self.connected = self.pad.poll()
        events = self.buttons.poll(self.connected, self.pad.buttons)
        if getattr(self, 'collect_human', False) and self.config.review == 'auto':
            events.difference_update({'keep', 'discard'})
        self.events.update(events)
        for event in events:
            self.event_times.setdefault(event, time.monotonic())
        hook = getattr(self, "event_hook", None)
        if hook and events:
            hook("buttons", dict(events=sorted(events), event_times=dict(self.event_times), connected=self.connected))
        now = self.node.get_clock().now().nanoseconds
        if self.next_reference is None:
            self.next_reference = now
        if now >= self.next_reference:
            reference = self.next_reference + ((now - self.next_reference) // 100_000_000) * 100_000_000
            self.next_reference = reference + 100_000_000
            window, status = self.runtime.window(reference)
            self.latest = None  # A failed window must not leave an old observation selectable.
            if window is not None and window[1].all():
                data, mask = window
                self.latest = (dict(data, history_mask=mask.astype(np.uint8)), reference)
                self.latest_eef_time = status["source_receive_ns"]["eef"]
                self.latest_status = status
        elif now < self.next_reference - 100_000_000:
            raise InteractionUnavailable("ROS clock moved backwards")

    def _manual_reset_tick(self):
        """Manual positioning between episodes; never a training transition."""
        if not getattr(self, "allow_manual_reset", False) or self.publisher is None:
            return
        held = self.connected and self.pad.buttons.get(BTN_TR, False)
        if getattr(self, 'reset_requires_release', False):
            if not self.connected or held:
                return
            self.reset_requires_release = False
        now = time.monotonic()
        if held and now >= getattr(self, "next_reset_tick", 0.):
            self._publish(self.mapping.action(self.pad.axes).astype(np.float32))
            self.next_reset_tick = now + 1 / self.config.hz
        elif not held and getattr(self, "reset_held", False):
            self.stop()
        self.reset_held = held

    def wait_start(self):
        review_hint = ('有效回合自动保留；' if self.config.review == 'auto' else
                       f'保留={self.config.keep_button}；丢弃={self.config.discard_button}；')
        print(f"等待开始={self.config.start_button}；成功={self.config.success_button}；"
              f"不成功结束={self.config.stop_button}；{review_hint}RB人工复位。", flush=True)
        self.reset_held = False
        self.reset_requires_release = True
        self.next_reset_tick = 0.
        self.events.clear()
        self.event_times.clear()
        while True:
            self._pump()
            if not self.connected:
                self._manual_reset_tick()
                self.events.clear()
                self.event_times.clear()
                continue
            if "start" in self.events:
                self.stop()
                self.reset_held = False
                self.events.clear()
                self.last_owner = None
                started = self.event_times["start"]
                self.event_times.clear()
                return started
            self._manual_reset_tick()
            self.events.clear()
            self.event_times.clear()

    def reset_history(self):
        self.runtime.reset()
        self.next_reference = None
        self.latest = None

    def observe(self, deadline):
        while time.monotonic() < deadline:
            self._pump()
            if self.publisher is not None and "disconnect" in self.events:
                raise InteractionUnavailable("gamepad disconnected")
            if self.latest is not None:
                return self.latest
        raise InteractionUnavailable("no fresh full history before deadline")

    def _publish(self, action, command_id=None):
        if self.publisher is None:
            raise InteractionUnavailable("preview cannot generate executed-action transitions; use --execute")
        competitors = getattr(self, 'competing_topics', ["/omi/action/manual_decision"])
        if any(self.node.count_publishers(t) > 0 for t in competitors if t != self.topic):
            raise InteractionUnavailable("another manual controller is active")
        if self.node.count_publishers(self.topic) != 1:
            raise InteractionUnavailable("another publisher owns final command topic")
        from std_msgs.msg import Float64MultiArray, MultiArrayDimension
        msg = Float64MultiArray(data=wire_action(action, self.convention))
        if command_id:
            msg.layout.dim = [MultiArrayDimension(label=command_id, size=6, stride=6)]
        sent_ns = self.node.get_clock().now().nanoseconds
        wire = list(msg.data)
        trace = dict(version="omi-command-trace-v1", command_id=command_id, command_topic=self.topic,
            command_send_ns=sent_ns, observation_reference_ns=getattr(self, "command_anchor_ns", None) if command_id else None,
            action_source=self.last_owner if command_id else ("manual_reset" if np.any(action) else "stop"),
            label_candidate=bool(command_id),
            action_m_rad=np.asarray(action, dtype=float).tolist(),
            normalized_action=self.config.normalized_action(action).tolist(),
            action_contract=self.config.replay_contract()["action_contract"],
            wire_action=wire, wire_units="mm,SDK_ABC_degrees", output_convention=self.convention,
            execution_confirmed=False)
        self.publisher.publish(msg)
        self.last_command_trace = trace
        trace_publisher = getattr(self, "trace_publisher", None)
        if trace_publisher is not None:
            from std_msgs.msg import String
            trace_publisher.publish(String(data=json.dumps(trace, allow_nan=False)))
        return wire

    def interact(self, action, anchor_stamp, deadline):
        self._pump()
        if not self.connected or "disconnect" in self.events:
            raise InteractionUnavailable("gamepad disconnected")
        now = self.node.get_clock().now().nanoseconds
        if 'manual_stop' in self.events:
            self.stop()
            raise EpisodeManualStop('manual_stop_between_commands')
        if "success" in self.events and self.event_times.get("success", float('inf')) < deadline:
            self.stop()
            raise EpisodeSuccess("success_between_commands")
        if time.monotonic() >= deadline:
            raise EpisodeTimeout("deadline passed before command")
        if not 0 <= now - anchor_stamp < 100_000_000:
            raise InteractionUnavailable("inference missed 100ms command freshness deadline")
        rb = self.pad.buttons.get(BTN_TR, False)
        collection = getattr(self, "collect_human", False)
        source = "human" if rb or collection else "policy"
        if self.human_only and source != "human":
            raise InteractionUnavailable("offline demo requires RB before sending any command")
        # Each policy is computed for the current anchor; no queued candidate is reused.
        self.last_owner = source
        adopted = (self.mapping.action(self.pad.axes).astype(np.float32) if rb else
                   np.zeros(6, np.float32) if collection else action.copy())
        if "discard" in self.events:
            raise InteractionUnavailable("operator aborted episode")
        command_id = "hil:" + uuid.uuid4().hex
        self.command_anchor_ns = anchor_stamp
        wire = self._publish(adopted, command_id)
        command_trace = dict(getattr(self, "last_command_trace", {}))
        sent_ns = self.node.get_clock().now().nanoseconds
        receipt = None
        stopped = False
        end_wait = min(deadline + .15, time.monotonic() + .25)
        while time.monotonic() < end_wait:
            self._pump()
            receipt = self.receipts.get(command_id, receipt)
            if not stopped and (time.monotonic() >= deadline or "success" in self.events or 'manual_stop' in self.events):
                self.stop()
                stopped = True
            if "disconnect" in self.events or "discard" in self.events:
                raise InteractionUnavailable("operator disconnected/aborted after command")
            if receipt is not None:
                if not receipt.get("accepted") or receipt.get("delta_frame") != "base" or receipt.get("arm") != "A" or receipt.get("wire_action") != wire:
                    raise InteractionUnavailable("receiver rejected/modified command or uses a different frame")
                if receipt.get("finished") and self.latest is not None and self.latest[1] > sent_ns:
                    # Actual EEF feedback must postdate the command, not just the window lattice.
                    if self.latest_eef_time > sent_ns:
                        events, self.events = self.events, set()
                        times, self.event_times = self.event_times, {}
                        return Interaction(*self.latest, adopted, source, events,
                            command_status=receipt["status"] + "_not_execution_confirmed", event_times=times,
                            audit=dict(command_id=command_id, command_topic=self.topic if hasattr(self, "topic") else "/omi/action/decision",
                                       command_send_ns=sent_ns, wire_action=wire, command_trace=command_trace,
                                       receipt=receipt, next_observation_status=getattr(self, "latest_status", {})))
        raise InteractionUnavailable("missing command receipt or causal next observation")

    def wait_review(self):
        self.reset_requires_release = True
        self.events.clear()
        self.event_times.clear()
        print("回合结束：A 保留整段，B 丢弃整段；先松开再按RB可人工复位。", flush=True)
        while True:
            self._pump()
            self._manual_reset_tick()
            if self.connected and "discard" in self.events:
                self.events.clear()
                self.stop()
                return False
            if self.connected and "keep" in self.events:
                self.events.clear()
                self.stop()
                return True
            self.events.clear()

    def idle_tick(self):
        """No episode restart during disk drain; RB positioning remains available."""
        self._pump()
        self._manual_reset_tick()
        self.events.clear()
        self.event_times.clear()

    def stop(self):
        # Zero delta requests a hold; no new motion delta while idle/review.
        if (self.publisher is not None and self.rclpy.ok() and self.node.count_publishers(self.topic) == 1
                and all(self.node.count_publishers(t) == 0 for t in
                        getattr(self, 'competing_topics', ["/omi/action/manual_decision"]) if t != self.topic)):
            self._publish(np.zeros(6))

    def close(self):
        self.pad.close()
        self.node.destroy_node()
        if self.owns_context and self.rclpy.ok():
            self.rclpy.shutdown()
