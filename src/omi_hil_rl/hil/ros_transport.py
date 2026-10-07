"""ROS observation collector and tagged final-command transport, lazy ROS imports."""
import json
import time
import uuid

import numpy as np

from .environment import ButtonEvents, Interaction, InteractionUnavailable, EpisodeTimeout, EpisodeSuccess, EpisodeManualStop
from omi_hil_rl.real.gamepad_control import Mapping, BTN_TR, wire_action
from omi_hil_rl.real.gamepad_home import GamepadHome
from omi_hil_rl.real.linux_gamepad import LinuxGamepad
from omi_hil_rl.training.stack_shadow import StackObservations


class RosTransport:
    def __init__(self, config, base_contract, *, execute=False, gamepad="/dev/input/js0",
                 topic="/omi/action/decision", convention="sdk-x-forward-z-left", rgb_max_age_ms=None,
                 home_button_code=None, gripper=None):
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
        self.gripper = gripper
        self.home = GamepadHome(self.node, button_code=home_button_code, require_rb=False) if home_button_code is not None else None
        self.home_active = False
        self.home_requires_release = True
        self.home_status = ''
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
            hook = getattr(self, 'receipt_hook', None)
            if hook is not None:
                hook(receipt)
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
        transitions = getattr(self.pad, 'button_events', ())
        if getattr(self, 'log_buttons', False):
            pressed = tuple(sorted(code for code, held in self.pad.buttons.items() if held))
            if transitions or pressed != getattr(self, 'last_pressed_buttons', ()):
                print(f'手柄按键：当前={list(pressed)}；事件={list(transitions)}；连接={self.connected}', flush=True)
            self.last_pressed_buttons = pressed
        gripper = getattr(self, 'gripper', None)
        if gripper is not None:
            gripper.tick(self.connected, self.pad.buttons, transitions)
        events = self.buttons.poll(self.connected, self.pad.buttons, transitions)
        if self.config.review == 'auto':
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
            self.latest_status = status  # Keep failed-window reasons for startup diagnostics too.
            self.latest = None  # A failed window must not leave an old observation selectable.
            if window is not None and window[1].all():
                data, mask = window
                self.latest = (dict(data, history_mask=mask.astype(np.uint8)), reference)
                self.latest_eef_time = status["source_receive_ns"]["eef"]
                self.latest_status = status
        elif now < self.next_reference - 100_000_000:
            raise InteractionUnavailable("ROS clock moved backwards")
        pipeline = getattr(self, 'policy_pipeline', None)
        if pipeline is not None:
            rb = bool(self.pad.buttons.get(BTN_TR, False))
            self._pipeline_released = bool(getattr(self, '_pipeline_rb', False) and not rb)
            interrupted = (not self.connected or rb or bool(
                self.events & {'success', 'manual_stop', 'disconnect', 'discard'}))
            if interrupted or rb != getattr(self, '_pipeline_rb', rb) or self.latest is None:
                pipeline.invalidate()
            self._pipeline_rb = rb
            pipeline.check()
            if not interrupted and self.latest is not None:
                pipeline.offer(*self.latest)

    def _handoff_ready(self):
        """Keep the exact next_obs, but wait for a newer window if receipt aged it.

        Half a period is reserved for validation/snapshot and pre-send pumping.
        The independent 100ms send gate remains authoritative.
        """
        pipeline = getattr(self, 'policy_pipeline', None)
        if pipeline is None:
            return True
        if self.latest is None:
            return False
        age = self.node.get_clock().now().nanoseconds - self.latest[1]
        if not 0 <= age < 50_000_000:
            return False
        if self.pad.buttons.get(BTN_TR, False):
            return True
        return pipeline.get(self.latest[1]) is not None

    def _manual_reset_tick(self):
        """Manual positioning between episodes; never a training transition."""
        if not getattr(self, "allow_manual_reset", False) or self.publisher is None:
            return False
        home = getattr(self, 'home', None)
        if home is not None:
            if getattr(self, 'home_requires_release', False):
                if self.connected and not self.pad.buttons.get(home.button_code, False):
                    self.home_requires_release = False
                    home.previous_x = False
                else:
                    home.previous_x = True
                command = None
            else:
                command = home.tick(self.connected, self.pad.buttons,
                                    getattr(self.pad, 'button_events', ()))
            if home.status != self.home_status:
                print('Back回位：' + home.status, flush=True)
                self.home_status = home.status
            active = (self.connected and bool(self.pad.buttons.get(home.button_code, False))
                      or home.future is not None or home.plan is not None or command is not None)
            if active:
                if command is not None and np.any(command[1]):
                    self._publish(command[1], convention='sdk-base-aligned', source='human_home')
                elif not self.home_active:
                    self.stop()
                self.home_active = True
                self.reset_held = False
                self.reset_requires_release = True
                return True
            if self.home_active:
                self.stop()
                self.home_active = False
                self.reset_requires_release = True
                return True
        held = self.connected and self.pad.buttons.get(BTN_TR, False)
        if getattr(self, 'reset_requires_release', False):
            if not self.connected or held:
                return False
            self.reset_requires_release = False
        now = time.monotonic()
        if held and now >= getattr(self, "next_reset_tick", 0.):
            self._publish(self.mapping.action(self.pad.axes).astype(np.float32))
            self.next_reset_tick = now + 1 / self.config.hz
        elif not held and getattr(self, "reset_held", False):
            self.stop()
        self.reset_held = held
        return False

    def wait_start(self):
        review_hint = ('有效回合自动保留；' if self.config.review == 'auto' else
                       f'保留={self.config.keep_button}；丢弃={self.config.discard_button}；')
        home_hint = f'Back({self.home.button_code})自动回home；' if self.home is not None else ''
        print(f"等待开始={self.config.start_button}；成功={self.config.success_button}；"
              f"不成功结束={self.config.stop_button}；{review_hint}RB人工复位；{home_hint}", flush=True)
        self.reset_held = False
        self.reset_requires_release = True
        self.next_reset_tick = 0.
        queued_start = bool(getattr(self, 'queue_start_during_save', False) and
                            self.connected and 'start' in self.events)
        self.queue_start_during_save = False
        self.events.clear()
        self.event_times.clear()
        if queued_start:
            self.events.add('start')
            # The new episode clock starts only after saving has finished.
            self.event_times['start'] = time.monotonic()
            print('下一回合：已收到保存期间的 Start；现在开始。', flush=True)
        while True:
            self._pump()
            if not self.connected:
                self._manual_reset_tick()
                self.events.clear()
                self.event_times.clear()
                continue
            home_active = self._manual_reset_tick()
            if "start" in self.events and not home_active:
                self.stop()
                self.reset_held = False
                self.events.clear()
                self.last_owner = None
                self.home_requires_release = True
                started = self.event_times["start"]
                self.event_times.clear()
                return started
            self.events.clear()
            self.event_times.clear()

    def reset_history(self):
        if getattr(self, 'policy_pipeline', None) is not None:
            self.policy_pipeline.invalidate()
        self.runtime.reset()
        self.next_reference = None
        self.latest = None

    def observe(self, deadline):
        print('WARMUP: 开始键已收到；正在准备完整观测。RB需先松开再按才能人工调整；观测完整后进入ACTIVE。', flush=True)
        next_log = 0.
        while time.monotonic() < deadline:
            self._pump()
            if self.publisher is not None and "disconnect" in self.events:
                raise InteractionUnavailable("gamepad disconnected")
            if self.events & {'success', 'manual_stop'}:
                raise InteractionUnavailable('operator ended episode during observation warmup')
            # Startup/warmup must not monopolize the gamepad when a sensor is
            # missing. These are reset actions, never fabricated training steps.
            home_active = self._manual_reset_tick()
            if time.monotonic() >= next_log:
                self.warmup_diagnostics = self._warmup_diagnostics()
                print('WARMUP_STATUS: ' + json.dumps(self.warmup_diagnostics), flush=True)
                next_log = time.monotonic()+1.
            if home_active:
                continue
            if self.latest is not None and self._handoff_ready():
                if getattr(self, 'reset_held', False):
                    self.stop()
                    self.reset_held = False
                return self.latest
        self.warmup_diagnostics = self._warmup_diagnostics()
        raise InteractionUnavailable("no fresh full history before deadline: " +
                                     json.dumps(self.warmup_diagnostics))

    def _warmup_diagnostics(self):
        runtime = getattr(self, 'runtime', None)
        status = getattr(self, 'latest_status', {})
        latest = getattr(runtime, 'latest', {})
        missing = [k for k in getattr(runtime, 'topics', {}).values() if k not in latest]
        pipeline = getattr(self, 'policy_pipeline', None)
        candidate = pipeline.get(self.latest[1]) if pipeline is not None and self.latest is not None else None
        return dict(window_reason=status.get('reason'),
                    full_history=self.latest is not None,
                    history_frames=sum(status.get('history_mask', [])),
                    missing_since_reset=missing,
                    received_total=dict(getattr(runtime, 'counts', {})),
                    rejected_total=dict(getattr(runtime, 'rejected', {})),
                    connected=getattr(self, 'connected', False),
                    rb=bool(getattr(getattr(self, 'pad', None), 'buttons', {}).get(BTN_TR, False)),
                    policy_candidate_ready=candidate is not None)

    def _publish(self, action, command_id=None, *, convention=None, source=None):
        if self.publisher is None:
            raise InteractionUnavailable("preview cannot generate executed-action transitions; use --execute")
        competitors = getattr(self, 'competing_topics', ["/omi/action/manual_decision"])
        if any(self.node.count_publishers(t) > 0 for t in competitors if t != self.topic):
            raise InteractionUnavailable("another manual controller is active")
        if self.node.count_publishers(self.topic) != 1:
            raise InteractionUnavailable("another publisher owns final command topic")
        from std_msgs.msg import Float64MultiArray, MultiArrayDimension
        output_convention = self.convention if convention is None else convention
        msg = Float64MultiArray(data=wire_action(action, output_convention))
        if command_id:
            msg.layout.dim = [MultiArrayDimension(label=command_id, size=6, stride=6)]
        sent_ns = self.node.get_clock().now().nanoseconds
        wire = list(msg.data)
        trace = dict(version="omi-command-trace-v1", command_id=command_id, command_topic=self.topic,
            command_send_ns=sent_ns, observation_reference_ns=getattr(self, "command_anchor_ns", None) if command_id else None,
            action_source=self.last_owner if command_id else source or ("manual_reset" if np.any(action) else "stop"),
            label_candidate=bool(command_id),
            action_m_rad=np.asarray(action, dtype=float).tolist(),
            normalized_action=self.config.normalized_action(action).tolist() if command_id else None,
            action_contract=self.config.replay_contract()["action_contract"],
            wire_action=wire, wire_units="mm,SDK_ABC_degrees", output_convention=output_convention,
            execution_confirmed=False)
        self.publisher.publish(msg)
        self.last_command_trace = trace
        trace_publisher = getattr(self, "trace_publisher", None)
        if trace_publisher is not None:
            from std_msgs.msg import String
            trace_publisher.publish(String(data=json.dumps(trace, allow_nan=False)))
        return wire

    def interact(self, action, anchor_stamp, deadline):
        pump_started = time.monotonic_ns()
        self._pump()
        pump_ms = (time.monotonic_ns()-pump_started)/1e6
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
            timing = dict(getattr(self, 'action_timing', {}))
            timing.update(anchor_ns=anchor_stamp, checked_ros_ns=now,
                          total_age_ms=(now-anchor_stamp)/1e6, pre_send_pump_ms=pump_ms,
                          reference_basis='local_ros_100ms_lattice_not_camera_header',
                          sensor_rejections=dict(getattr(getattr(self, 'runtime', None), 'rejected', {})))
            print('COMMAND_TIMING_FAILURE: ' + json.dumps(timing), flush=True)
            report_path = getattr(self, 'timing_report_path', None)
            if report_path is not None:
                from .exchange import atomic_json
                # Stop before diagnostic disk IO; no rejected action is published.
                self.stop()
                atomic_json(report_path, timing)
            raise InteractionUnavailable("inference missed 100ms command freshness deadline")
        rb = self.pad.buttons.get(BTN_TR, False)
        collection = getattr(self, "collect_human", False)
        source = "human" if rb or collection else "policy"
        pipeline = getattr(self, 'policy_pipeline', None)
        if pipeline is not None and source == 'policy':
            candidate = pipeline.get(anchor_stamp)
            if candidate is None:
                if getattr(self, '_pipeline_released', False):
                    # A release observed in this very pump invalidates all old
                    # candidates. Send an audited manual zero for this boundary,
                    # then hand off only after a new policy candidate is ready.
                    source = 'human'
                    action = np.zeros(6, np.float32)
                else:
                    raise InteractionUnavailable('policy candidate invalidated before command (RB/event/history change)')
            # Never use a candidate for a different observation, or a caller's
            # zero action produced before an RB-release edge was polled.
            else:
                action = self.config.physical_action(candidate[0])
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
        wait_started = time.monotonic()
        end_wait = min(deadline + .15, wait_started + .25)
        while time.monotonic() < end_wait:
            self._pump()
            receipt = self.receipts.get(command_id, receipt)
            if (pipeline is not None and source == 'policy' and
                    self.pad.buttons.get(BTN_TR, False) and not stopped):
                self.stop()  # RB takeover also interrupts an in-flight policy hold.
                stopped = True
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
                    ending = time.monotonic() >= deadline or bool(self.events & {'success', 'manual_stop'})
                    if self.latest_eef_time > sent_ns and (ending or self._handoff_ready()):
                        events, self.events = self.events, set()
                        times, self.event_times = self.event_times, {}
                        return Interaction(*self.latest, adopted, source, events,
                            command_status=receipt["status"] + "_not_execution_confirmed", event_times=times,
                            audit=dict(command_id=command_id, command_topic=command_trace.get('command_topic', getattr(self, 'topic', '/omi/action/decision')),
                                       command_send_ns=sent_ns, wire_action=wire, command_trace=command_trace,
                                       receipt=receipt, next_observation_status=getattr(self, "latest_status", {})))
        # The receipt and observation are independent inputs. Preserve which
        # condition missed the deadline before the caller stops the episode.
        if receipt is None:
            pairing_reason = 'no_command_receipt'
        elif not receipt.get('finished'):
            pairing_reason = 'receipt_not_finished'
        elif self.latest is None:
            pairing_reason = 'no_complete_next_observation'
        elif self.latest[1] <= sent_ns:
            pairing_reason = 'next_observation_not_after_command'
        elif getattr(self, 'latest_eef_time', 0) <= sent_ns:
            pairing_reason = 'eef_not_after_command'
        else:
            pairing_reason = 'next_observation_not_ready_for_handoff'
        self.stop()
        pairing = dict(reason=pairing_reason, command_id=command_id,
                       command_send_ns=sent_ns,
                       waited_ms=(time.monotonic() - wait_started) * 1000,
                       receipt=receipt,
                       latest_observation_reference_ns=self.latest[1] if self.latest is not None else None,
                       latest_eef_receive_ns=getattr(self, 'latest_eef_time', None),
                       latest_observation_status=getattr(self, 'latest_status', None),
                       received_total=dict(getattr(self.runtime, 'counts', {})),
                       rejected_total=dict(getattr(self.runtime, 'rejected', {})))
        self.last_pairing_failure = pairing
        print('COMMAND_PAIRING_FAILURE: ' + json.dumps(pairing, allow_nan=False), flush=True)
        report_path = getattr(self, 'pairing_report_path', None)
        if report_path is not None:
            from .exchange import atomic_json
            atomic_json(report_path, pairing)
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
        queued_start = bool(getattr(self, 'queue_start_during_save', False) and
                            self.connected and 'start' in self.events)
        if queued_start and not getattr(self, 'queued_start_reported', False):
            print('下一回合 Start 已收到；当前回合保存完成后开始。', flush=True)
            self.queued_start_reported = True
        self.events.clear()
        self.event_times.clear()
        if queued_start:
            self.events.add('start')
            self.event_times['start'] = time.monotonic()

    def stop(self):
        # Zero delta requests a hold; no new motion delta while idle/review.
        if (self.publisher is not None and self.rclpy.ok() and self.node.count_publishers(self.topic) == 1
                and all(self.node.count_publishers(t) == 0 for t in
                        getattr(self, 'competing_topics', ["/omi/action/manual_decision"]) if t != self.topic)):
            self._publish(np.zeros(6))

    def close(self):
        try:
            self.pad.close()
            self.node.destroy_node()
            if self.owns_context and self.rclpy.ok():
                self.rclpy.shutdown()
        finally:
            gripper = getattr(self, 'gripper', None)
            if gripper is not None:
                gripper.close()
