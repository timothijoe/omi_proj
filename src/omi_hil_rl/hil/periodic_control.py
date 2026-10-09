"""10Hz latest observations drive human commands and asynchronous inference.

No blocking command receipt/next-observation join in the publishing loop.
Raw periodic audit is not itself a training episode. Protected RL sessions opt
into background export of accepted-command segments; timing is diagnostic only.
"""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

import numpy as np

from .exchange import atomic_json


def _banner(message, color):
    line = f'========== {message} =========='
    if sys.stdout.isatty() and not os.environ.get('NO_COLOR'):
        line = f'\033[1;{color}m{line}\033[0m'
    print('\n' + line, flush=True)


class PeriodicClock:
    def __init__(self, start, period=.1):
        self.next = start
        self.period = period

    def due(self, now):
        if now < self.next:
            return None
        lag = now-self.next
        skipped = int(lag/self.period)
        self.next += (skipped+1)*self.period
        return dict(lateness_ms=lag*1000, skipped_ticks=skipped)


def choose_action(transport, used_stamp, verified):
    """Manual priority; stale/missing/reused policy candidates become zero."""
    if not transport.connected:
        raise RuntimeError('gamepad disconnected')
    human = bool(transport.pad.buttons.get(311, False))
    if getattr(transport, 'collect_human', False):
        if not verified:
            return np.zeros(6, np.float32), 'human', 'receiver_handshake', transport.latest, used_stamp
        action = (transport.mapping.action(transport.pad.axes).astype(np.float32) if human
                  else np.zeros(6, np.float32))
        return action, 'human', 'human', transport.latest, used_stamp
    source = 'human' if human else 'policy'
    latest = transport.latest
    if not verified:
        return np.zeros(6, np.float32), source, 'receiver_handshake', latest, used_stamp
    if human:
        return transport.mapping.action(transport.pad.axes).astype(np.float32), source, 'human', latest, used_stamp
    if latest is not None:
        observation, stamp = latest
        age = transport.node.get_clock().now().nanoseconds-stamp
        pipeline = getattr(transport, 'policy_pipeline', None)
        candidate = pipeline.get(stamp) if pipeline is not None else None
        if 0 <= age < 100_000_000 and stamp != used_stamp and candidate is not None:
            return transport.config.physical_action(candidate[0]), source, 'policy', latest, stamp
    return np.zeros(6, np.float32), source, 'no_fresh_unused_candidate', latest, used_stamp


def observation_action(transport, used_stamp, verified, *, policy=True):
    """Observation-triggered human commands and completion-triggered policy commands.

    None means no new command: it never means replace a slow inference with zero.
    """
    latest = transport.latest
    if latest is None:
        return None
    if policy and not getattr(transport, 'collect_human', False) and getattr(
            transport, 'arbitration_mode', 'immediate') == 'after-inference':
        pipeline = getattr(transport, 'policy_pipeline', None)
        result = pipeline.take() if pipeline is not None else None
        if result is None:
            return None
        observation, stamp, candidate, elapsed = result
        # Read human input when consuming the result, never latch it at inference start.
        rb = bool(transport.pad.buttons.get(311, False))
        source = 'human' if rb else 'policy'
        transport.last_arbitration = dict(mode='after-inference', rb=rb,
            observation_reference_ns=stamp, policy_candidate_normalized=candidate.tolist())
        if not verified[source]:
            action, gate = np.zeros(6, np.float32), 'receiver_handshake'
        elif rb:
            action, gate = transport.mapping.action(transport.pad.axes).astype(np.float32), 'human'
        else:
            action, gate = transport.config.physical_action(candidate), 'policy'
        return action, source, gate, (observation, stamp), stamp, elapsed
    stamp = latest[1]
    human = getattr(transport, 'collect_human', False) or bool(transport.pad.buttons.get(311, False))
    source = 'human' if human else 'policy'
    if not verified[source]:
        if stamp == used_stamp:
            return None
        return np.zeros(6, np.float32), source, 'receiver_handshake', latest, stamp, None
    if human:
        if stamp == used_stamp:
            return None
        action = (transport.mapping.action(transport.pad.axes).astype(np.float32)
                  if transport.pad.buttons.get(311, False) else np.zeros(6, np.float32))
        return action, 'human', 'human', latest, stamp, None
    if not policy:
        if stamp == used_stamp:
            return None
        return np.zeros(6, np.float32), source, 'policy_disabled', latest, stamp, None
    pipeline = getattr(transport, 'policy_pipeline', None)
    result = pipeline.take() if pipeline is not None else None
    if result is None:
        return None
    observation, stamp, action, elapsed = result
    return transport.config.physical_action(action), source, 'policy', (observation, stamp), stamp, elapsed


def pair_status(tick, following, receipts):
    """Conservative audit eligibility; never turn acceptance into completion."""
    if not tick['observation_present'] or following is None or not following['observation_present']:
        return 'missing_observation'
    if not (tick['observation_reference_ns'] <= tick['command_send_ns'] < following['observation_reference_ns']):
        return 'noncausal_observation_pair'
    matched = [r for r in receipts if r.get('command_id') == tick['command_id']]
    if not matched:
        return 'missing_receipt'
    completed = [r for r in matched if r.get('finished')]
    if not completed:
        return 'receipt_not_finished'
    last = completed[-1]
    if (last.get('wire_action') != tick['wire_action'] or last.get('arm') != 'A' or
            last.get('delta_frame') != 'base' or last.get('control_mode') != 'velocity_hold'):
        return 'receipt_contract_mismatch'
    if last.get('status') == 'queue_replaced' and following is not None:
        # The next scheduled command replaces velocity_hold at the nominal
        # boundary. That is not an execution-complete receipt, but it is a
        # normal accepted-command boundary when the prior command lived for
        # nearly a full cycle. Early replacement remains invalid.
        adopted = any(r.get('accepted') and r.get('status') == 'queue_accepted'
                      for r in matched)
        replaced_ns = last.get('timestamp_ns', -1)
        if (adopted and replaced_ns >= following.get('command_send_ns', float('inf')) and
                replaced_ns - tick['command_send_ns'] >= 80_000_000):
            return 'matched_not_execution_confirmed'
    if not last.get('accepted') or last.get('status') not in ('velocity_window_sent', 'velocity_zero_stopped'):
        return 'partial_or_replaced_command'
    return 'matched_not_execution_confirmed'


class PeriodicAudit:
    def __init__(self, run, episode, contract, version, *, training=False, timing_policy='strict'):
        self.run, self.contract, self.version, self.training = run, contract, version, training
        self.directory = Path(run)/'periodic_episodes'/episode
        self.directory.mkdir(parents=True, exist_ok=False)
        from .observation_storage import FrameWriter, VERSION
        self.frame_writer = FrameWriter(self.directory/'frames')
        self.tasks = queue.Queue(maxsize=256)
        self.error = None
        self.result = None
        self.closed = False
        self.timing_policy = timing_policy
        atomic_json(self.directory/'staging.json', dict(schema='omi-periodic-audit-v1',
                    episode=episode, contract=contract, policy_version=version, training_ready=False,
                    timing_policy=timing_policy, observation_storage_version=VERSION))
        self.thread = threading.Thread(target=self._work, name='periodic-audit-writer', daemon=True)
        self.thread.start()

    def submit(self, kind, value):
        if self.error:
            raise RuntimeError('periodic writer failed: '+self.error)
        if self.closed:
            raise RuntimeError('periodic writer closed')
        try:
            self.tasks.put_nowait((kind, value))
        except queue.Full:
            raise RuntimeError('periodic audit queue full; refusing silent recording loss')

    def _work(self):
        ticks, receipts, interruptions = [], [], []
        observations = {}
        try:
            with (self.directory/'receipts.jsonl').open('w') as log:
                while True:
                    kind, payload = self.tasks.get()
                    if kind == 'receipt':
                        receipts.append(payload)
                        log.write(json.dumps(payload)+'\n')
                        log.flush()
                    elif kind == 'interrupt':
                        interruptions.append(payload)
                    elif kind == 'observation':
                        stamp, observation, status = payload
                        folder = self.directory/'observations'
                        folder.mkdir(exist_ok=True)
                        metadata = dict(status, observation_reference_ns=stamp,
                                        observation_present=observation is not None)
                        observations[stamp] = metadata
                        self.frame_writer.write(folder/f'{stamp}.npz', metadata, observation)
                    elif kind == 'tick':
                        metadata, observation = payload
                        status = observations.get(metadata['observation_reference_ns'], {})
                        if status:
                            metadata = dict(metadata, observation_status=status,
                                eef_receive_ns=status.get('source_receive_ns', {}).get('eef'))
                        path = self.directory/f"{len(ticks):06d}.npz"
                        self.frame_writer.write(path, metadata, observation)
                        ticks.append(metadata)
                    elif kind == 'finish':
                        boundary, outcome = payload
                        boundary_meta = boundary[0] if boundary is not None else None
                        statuses = [pair_status(t, ticks[i+1] if i+1 < len(ticks) else boundary_meta, receipts)
                                    for i, t in enumerate(ticks)]
                        log.flush()
                        os.fsync(log.fileno())
                        atomic_json(self.directory/'pairing.json', statuses)
                        self.result = dict(outcome, ticks=len(ticks),
                            observation_ticks=len(observations), timing_policy=self.timing_policy,
                            pairing_is_diagnostic=self.timing_policy == 'diagnostic_only_v1',
                            matched_pairs=statuses.count('matched_not_execution_confirmed'),
                            invalid_pairs=len(ticks)-statuses.count('matched_not_execution_confirmed'),
                            nonzero_action_ticks=sum(any(abs(value) > 1e-7 for value in tick['normalized_action'])
                                                     for tick in ticks),
                            training_ready=False, schema='omi-periodic-audit-v1',
                            reason_for_separate_format='periodic velocity replacement; no legacy transition fabrication')
                        atomic_json(self.directory/'interruptions.json', interruptions)
                        if boundary is not None:
                            self.frame_writer.write(self.directory/'boundary.npz', boundary[0], boundary[1])
                        if self.training:
                            from .periodic_replay import convert
                            self.result.update(convert(self.directory, self.run, self.contract, self.version,
                                                       ticks, receipts, interruptions, boundary, outcome,
                                                       timing_policy=self.timing_policy, frame_writer=self.frame_writer))
                        elif self.timing_policy == 'diagnostic_only_v1':
                            from collections import Counter
                            from .periodic_replay import timing_diagnostics
                            diagnostics = [timing_diagnostics(t, ticks[i+1] if i+1 < len(ticks) else boundary_meta,
                                                              receipts, interruptions) for i, t in enumerate(ticks)]
                            atomic_json(self.directory/'timing_diagnostics.json', diagnostics)
                            self.result['timing_diagnostics'] = dict(Counter(reason for row in diagnostics for reason in row))
                        if self.result.get('timing_diagnostics'):
                            print('TRANSITION_TIMING: '+json.dumps(dict(
                                episode=outcome['episode'], diagnostic_only=True,
                                counts=self.result['timing_diagnostics'])), flush=True)
                        from .observation_storage import VERSION
                        self.result.update(observation_storage_version=VERSION,
                                           stored_observation_frames=len(self.frame_writer.written))
                        atomic_json(self.directory/'audit.json', self.result)
                        return
        except Exception as exc:
            self.error = repr(exc)

    def finish(self, boundary, outcome, tick=None):
        if not self.closed:
            while self.thread.is_alive() and not self.error:
                try:
                    self.tasks.put(('finish', (boundary, outcome)), timeout=.01)
                    break
                except queue.Full:
                    if tick: tick()
            self.closed = True
        while self.thread.is_alive():
            self.thread.join(.01)
            if tick: tick()
        if self.error:
            raise RuntimeError('periodic writer failed: '+self.error)
        return self.result


def run_periodic(actor, episodes, *, training=False):
    transport, config = actor.transport, actor.config
    if abs(config.hz-10.) > 1e-6:
        raise ValueError('periodic entry currently requires 10Hz contract')
    transport.allow_manual_reset = True
    transport.observation_driven = True
    if hasattr(transport, 'runtime'):
        transport.runtime.latest_mode = True
    arbitration_mode = (getattr(transport, 'arbitration_mode', 'immediate')
                        if getattr(actor, 'policy', False) and not getattr(transport, 'collect_human', False)
                        else 'immediate')
    transport.arbitration_mode = arbitration_mode
    actor.load()
    print(f'ARBITRATION_MODE: {arbitration_mode}; '+
          ('RB/joystick selected after each inference, including while RB is held' if arbitration_mode == 'after-inference'
           else 'RB takeover does not wait for inference'), flush=True)
    print('OBSERVATION_CONTROL: 100ms latest observation; infer then send; timing diagnostic only; '+
          ('background replay export' if training else 'audit-only recording'), flush=True)
    if getattr(transport, 'collect_human', False):
        print('PERIODIC_CONTROL: Start(315)进入回合；移动机械臂需持续按住RB(311)并推动摇杆。', flush=True)
    completed_episodes = 0
    total_transitions = 0
    total_nonzero_ticks = 0
    try:
        for episode_number in range(1, episodes + 1):
            actor.state('WAIT_START', control_mode='observation_driven_10hz',
                        timing_policy='diagnostic_only_v1', arbitration_mode=arbitration_mode, training_ready=False)
            if getattr(transport, 'collect_human', False):
                print(f'采集进度：等待第 {episode_number}/{episodes} 回合 Start；'
                      f'本次运行已完成 {completed_episodes} 回合，累计有效动作 {total_transitions} 条。', flush=True)
            elif training:
                _banner(f'等待第 {episode_number}/{episodes} 个 RL 回合：按 Start 开始；RB 可随时接管', '36')
            started = transport.wait_start()
            transport.start_episode()
            episode = uuid.uuid4().hex
            audit = PeriodicAudit(actor.run, episode, config.replay_contract(), actor.version, training=training,
                                  timing_policy='diagnostic_only_v1')
            def record_observation(stamp, latest, status):
                audit.submit('observation', (stamp, None if latest is None else latest[0], dict(status)))
            transport.observation_hook = record_observation
            if transport.latest is not None:
                record_observation(transport.latest[1], transport.latest, getattr(transport, 'latest_status', {}))
            monitor_start = getattr(actor, 'periodic_monitor_start', None)
            if monitor_start is not None:
                monitor_start(episode, started)
            known = {}
            unacknowledged = {}
            verified = {'human': False, 'policy': False}
            fault = None
            fault_receipt = None
            def receipt_hook(receipt):
                nonlocal fault, fault_receipt
                if receipt.get('command_id') not in known:
                    return
                audit.submit('receipt', dict(receipt))
                expected_source, expected_wire = known[receipt['command_id']]
                unacknowledged.pop(receipt['command_id'], None)
                monitor = getattr(actor, 'telemetry', None)
                if monitor is not None:
                    monitor.update(receiver=dict(receipt, observed_ns=time.time_ns()))
                try:
                    duration = float(receipt.get('nominal_duration_s', 0))
                except (TypeError, ValueError):
                    duration = float('nan')
                if (receipt.get('control_mode') != 'velocity_hold' or
                        receipt.get('arm') != 'A' or receipt.get('delta_frame') != 'base' or
                        receipt.get('wire_action') != expected_wire or
                        receipt.get('action_source') != expected_source or
                        not np.isfinite(duration) or abs(duration-.1) > .001):
                    fault = 'receiver is not base/ArmA/10Hz velocity_hold'
                elif receipt.get('accepted'):
                    verified[expected_source] = True
                elif receipt.get('status') != 'queue_replaced':
                    fault = 'receiver fault: '+str(receipt.get('status'))
                if fault and fault_receipt is None:
                    fault_receipt = dict(receipt)
                    print('RECEIVER_FAULT: '+json.dumps(fault_receipt, ensure_ascii=False), flush=True)
            transport.receipt_hook = receipt_hook
            deadline = started+config.episode_seconds
            used_stamp = None
            count = 0
            outcome = dict(episode=episode, policy_version=actor.version, arbitration_mode=arbitration_mode,
                           success=False, reason='interrupted')
            telemetry = getattr(actor, 'telemetry', None)
            last_owner = None
            last_rb = bool(transport.pad.buttons.get(311, False))
            try:
                actor.state('ACTIVE', control_mode='observation_driven_10hz',
                            timing_policy='diagnostic_only_v1', arbitration_mode=arbitration_mode, training_ready=False)
                if getattr(transport, 'collect_human', False):
                    print('ACTIVE: RB+摇杆控制；松开RB为零动作；308成功、307提前结束，否则到时停止。',
                          flush=True)
                    _banner('已开始采集：现在按住 RB 并推动摇杆控制机械臂', '36')
                    print('按 308 标记任务成功；按 307 提前结束；到时自动结束。\n', flush=True)
                elif training:
                    policy_hint = ('策略正在推理' if getattr(actor, 'policy', False) else
                                   '策略未启用，默认发送零动作')
                    _banner(f'RL 回合已开始：{policy_hint}；按住 RB 用摇杆接管', '36')
                    print('按 308 标记成功；按 307 提前结束；到时自动结束。\n', flush=True)
                while True:
                    transport._pump()
                    now = time.monotonic()
                    if not transport.connected:
                        raise RuntimeError('gamepad disconnected')
                    if fault:
                        raise RuntimeError(fault)
                    if unacknowledged and now-min(unacknowledged.values()) > 1.:
                        raise RuntimeError('receiver receipt link silent for 1s; stopped (not a per-command wait)')
                    if audit.error:
                        raise RuntimeError('periodic writer failed: '+audit.error)
                    if 'manual_stop' in transport.events:
                        outcome['reason'] = 'manual_stop'
                        break
                    if 'success' in transport.events and transport.event_times.get('success', now) < deadline:
                        outcome.update(reason='success', success=True)
                        break
                    if now >= deadline:
                        outcome['reason'] = 'timeout'
                        break
                    # Immediate mode handles RB edges here; deferred mode switches only after inference.
                    rb = bool(transport.pad.buttons.get(311, False))
                    if arbitration_mode == 'immediate' and rb != last_rb and last_owner is not None:
                        audit.submit('interrupt', transport.node.get_clock().now().nanoseconds)
                        transport.stop()
                        last_owner = None
                    last_rb = rb
                    selected = observation_action(transport, used_stamp, verified,
                                                  policy=getattr(actor, 'policy', True))
                    if selected is None:
                        continue
                    action, source, gate, latest, used_stamp, inference_ms = selected
                    if arbitration_mode == 'after-inference' and last_owner is not None and source != last_owner:
                        audit.submit('interrupt', transport.node.get_clock().now().nanoseconds)
                        transport.stop()
                    command_id = 'hil:'+uuid.uuid4().hex
                    transport.last_owner = source
                    transport.command_anchor_ns = latest[1] if latest is not None else None
                    wire = transport._publish(action, command_id)
                    known[command_id] = (source, wire)
                    unacknowledged[command_id] = now
                    last_owner = source
                    sent_ns = transport.last_command_trace.get('command_send_ns', transport.node.get_clock().now().nanoseconds)
                    delay_ms = (sent_ns-latest[1])/1e6
                    timing = dict(lateness_ms=delay_ms, skipped_ticks=0)
                    if delay_ms > 100 or (inference_ms is not None and inference_ms > 100):
                        print('ACTION_TIMING: '+json.dumps(dict(command_id=command_id,
                            observation_reference_ns=latest[1], observation_to_send_ms=delay_ms,
                            inference_ms=inference_ms, diagnostic_only=True)), flush=True)
                    metadata = dict(command_id=command_id, action_source=source, gate=gate,
                        arbitration_mode=arbitration_mode,
                        arbitration=getattr(transport, 'last_arbitration', None),
                        timing_policy='diagnostic_only_v1', inference_ms=inference_ms,
                        policy_version=actor.version, observation_present=latest is not None,
                        observation_reference_ns=transport.command_anchor_ns,
                        eef_receive_ns=getattr(transport, 'latest_eef_time', None),
                        command_send_ns=sent_ns,
                        normalized_action=config.normalized_action(action).tolist(), wire_action=wire,
                        command_trace=dict(transport.last_command_trace), **timing)
                    if telemetry is not None:
                        telemetry.update(episode=episode, tick=count, remaining_s=max(0., deadline-now),
                            arbitration=dict(source=source, gate=gate, command_id=command_id,
                                mode=arbitration_mode, rb=rb,
                                normalized_action=metadata['normalized_action'], wire_action=wire,
                                inference_ms=inference_ms, observation_reference_ns=latest[1],
                                observation_to_send_ms=delay_ms,
                                trace=metadata['command_trace'], receiver_verified=dict(verified),
                                lateness_ms=timing['lateness_ms'], skipped_ticks=timing['skipped_ticks']),
                            audit_queue=audit.tasks.qsize())
                    audit.submit('tick', (metadata, latest[0] if latest is not None else None))
                    count += 1
                    if count % 10 == 0:
                        moving = bool(np.any(np.abs(action) > 1e-7))
                        print(f'PERIODIC: ticks={count} source={source} gate={gate} '
                              f'rb={bool(transport.pad.buttons.get(311, False))} '
                              f'nonzero_action={moving} receiver_verified={verified}', flush=True)
            except Exception as exc:
                outcome['reason'] = str(exc)
                print('PERIODIC_STOP: '+str(exc), flush=True)
            finally:
                boundary = None
                if fault_receipt is not None:
                    outcome['receiver_fault'] = fault_receipt
                stop_ns = transport.node.get_clock().now().nanoseconds
                if training and transport.latest is not None:
                    boundary = (dict(observation_present=True, observation_reference_ns=transport.latest[1],
                                     eef_receive_ns=getattr(transport, 'latest_eef_time', None),
                                     command_send_ns=transport.node.get_clock().now().nanoseconds), transport.latest[0])
                transport.stop()
                monitor_end = getattr(actor, 'periodic_monitor_end', None)
                if monitor_end is not None:
                    monitor_end(episode)
                if getattr(transport, 'collect_human', False):
                    # A Start pressed during the active episode is not a request
                    # to restart. Only presses after the stop may be queued.
                    transport.events.discard('start')
                    transport.event_times.pop('start', None)
                    transport.queue_start_during_save = True
                    transport.queued_start_reported = False
                if getattr(transport, 'collect_human', False):
                    if outcome['reason'] == 'success':
                        verdict = '任务成功：已收到 308 成功按键'
                    elif outcome['reason'] == 'manual_stop':
                        verdict = '任务未标记成功：已收到 307 提前结束按键'
                    elif outcome['reason'] == 'timeout':
                        verdict = '任务未标记成功：已达到回合时限'
                    else:
                        verdict = '回合异常停止：' + outcome['reason']
                    color = ('32' if outcome['reason'] == 'success' else
                             '33' if outcome['reason'] in ('manual_stop', 'timeout') else '31')
                    english_result = {'success': 'SUCCESS', 'manual_stop': 'MANUAL_STOP',
                                      'timeout': 'TIMEOUT'}.get(outcome['reason'], 'ERROR')
                    print(f"EPISODE_RESULT: {english_result} success={outcome['success']} "
                          f"reason={outcome['reason']}", flush=True)
                    _banner(verdict, color)
                elif training:
                    if outcome['reason'] == 'success':
                        _banner('RL 回合已标记成功：收到 308；正在核对成功奖励能否入池', '32')
                    elif outcome['reason'] == 'manual_stop':
                        _banner('RL 回合未标记成功：收到 307 提前结束', '33')
                    elif outcome['reason'] == 'timeout':
                        _banner('RL 回合未标记成功：已达到回合时限', '33')
                    else:
                        _banner('RL 回合异常停止：' + outcome['reason'], '31')
                # Stop first; callbacks may finish late. Never wait in the send loop.
                try:
                    drain_until = time.monotonic()+.3
                    while time.monotonic() < drain_until:
                        transport._pump()
                        # Capture a following observation tick, without waiting for
                        # EEF freshness/causality, before permitting manual reset.
                        if (transport.latest is not None and
                                (used_stamp is None or transport.latest[1] > used_stamp) and
                                (boundary is None or boundary[0]['observation_reference_ns'] <= (used_stamp or 0))):
                            boundary = (dict(observation_present=True,
                                observation_reference_ns=transport.latest[1],
                                eef_receive_ns=getattr(transport, 'latest_eef_time', None),
                                **({'terminal_success_stop_ns': stop_ns} if outcome['success'] else {}),
                                command_send_ns=transport.node.get_clock().now().nanoseconds), transport.latest[0])
                finally:
                    transport.receipt_hook = None
                    transport.observation_hook = None
                    # No reset is permitted until the boundary is captured.
                    if training and not getattr(transport, 'collect_human', False):
                        _banner('正在保存 RL 回合：等待本地写盘与有效片段校验完成', '33')
                    save_started = time.monotonic()
                    actor.state('SAVING', episode=episode)
                    result = audit.finish(boundary, outcome, tick=transport.idle_tick)
                    save_seconds = time.monotonic() - save_started
                    actor.state('EPISODE_RECORDED', audit=result, save_seconds=save_seconds)
                    print('PERIODIC_SAVED: '+json.dumps(result), flush=True)
                    if training and not getattr(transport, 'collect_human', False):
                        transitions = result.get('transitions', 0)
                        if result.get('training_ready'):
                            label = ('成功奖励已记录' if result.get('success_label_recorded') else
                                     '没有成功奖励标签')
                            _banner(f'本地保存完成（{save_seconds:.1f} 秒）：有效动作 {transitions} 条；'
                                    f'{label}；训练片段待 Learner 异步导入', '32')
                        else:
                            _banner(f'本地审计已保存（{save_seconds:.1f} 秒）：有效动作 {transitions} 条；'
                                    '本回合没有可训练片段', '33')
                    if getattr(transport, 'collect_human', False):
                        completed_episodes += 1
                        total_transitions += result.get('transitions', 0)
                        total_nonzero_ticks += result.get('nonzero_action_ticks', 0)
                        readiness = '可进入训练池' if result.get('training_ready') else '未进入训练池'
                        _banner(f"数据保存完成：有效动作 {result.get('transitions', 0)} 条，"
                                f"非零动作 {result.get('nonzero_action_ticks', 0)} 次；{readiness}",
                                '32' if result.get('training_ready') else '33')
                        print(f'采集进度：已完成 {completed_episodes}/{episodes} 回合；'
                              f'本次运行累计有效动作 {total_transitions} 条，非零动作 {total_nonzero_ticks} 次。',
                              flush=True)
                    if training and result.get('training_ready'):
                        actor.finished(dict(keep=True, reason=outcome['reason'], episode=episode))
    finally:
        transport.stop()
        transport.receipt_hook = None
        transport.observation_hook = None
        actor.close_pipeline()
