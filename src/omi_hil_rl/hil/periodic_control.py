"""Best-effort 10Hz velocity publisher with independent asynchronous audit.

No blocking command receipt/next-observation join in the publishing loop.
Raw periodic audit is not itself a training episode. Protected RL sessions opt
into background validation and export of contiguous accepted-command segments.
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
    def __init__(self, run, episode, contract, version, *, training=False):
        self.run, self.contract, self.version, self.training = run, contract, version, training
        self.directory = Path(run)/'periodic_episodes'/episode
        self.directory.mkdir(parents=True, exist_ok=False)
        self.tasks = queue.Queue(maxsize=256)
        self.error = None
        self.result = None
        self.closed = False
        atomic_json(self.directory/'staging.json', dict(schema='omi-periodic-audit-v1',
                    episode=episode, contract=contract, policy_version=version, training_ready=False))
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
                    elif kind == 'tick':
                        metadata, observation = payload
                        arrays = {} if observation is None else {'observation__'+k: v for k, v in observation.items()}
                        arrays['metadata'] = np.asarray(json.dumps(metadata))
                        path = self.directory/f"{len(ticks):06d}.npz"
                        temporary = path.with_suffix('.tmp')
                        with temporary.open('wb') as stream:
                            np.savez_compressed(stream, **arrays)
                            stream.flush()
                            os.fsync(stream.fileno())
                        temporary.replace(path)
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
                            matched_pairs=statuses.count('matched_not_execution_confirmed'),
                            invalid_pairs=len(ticks)-statuses.count('matched_not_execution_confirmed'),
                            nonzero_action_ticks=sum(any(abs(value) > 1e-7 for value in tick['normalized_action'])
                                                     for tick in ticks),
                            training_ready=False, schema='omi-periodic-audit-v1',
                            reason_for_separate_format='periodic velocity replacement; no legacy transition fabrication')
                        atomic_json(self.directory/'interruptions.json', interruptions)
                        if boundary is not None:
                            with (self.directory/'boundary.npz').open('wb') as stream:
                                np.savez_compressed(stream, metadata=np.asarray(json.dumps(boundary[0])),
                                                    **{'observation__'+k: v for k, v in boundary[1].items()})
                                stream.flush()
                                os.fsync(stream.fileno())
                        if self.training:
                            from .periodic_replay import convert
                            self.result.update(convert(self.directory, self.run, self.contract, self.version,
                                                       ticks, receipts, interruptions, boundary, outcome))
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
    actor.load()
    source_hint = ('human-only RB/zero actions' if getattr(transport, 'collect_human', False)
                   else 'missing candidate=ZERO')
    print('PERIODIC_CONTROL: 100ms target; no receipt wait; '+source_hint+'; '+
          ('background replay validation' if training else 'audit-only recording'), flush=True)
    if getattr(transport, 'collect_human', False):
        print('PERIODIC_CONTROL: Start(315)进入回合；移动机械臂需持续按住RB(311)并推动摇杆。', flush=True)
    completed_episodes = 0
    total_transitions = 0
    total_nonzero_ticks = 0
    try:
        for episode_number in range(1, episodes + 1):
            actor.state('WAIT_START', control_mode='periodic_100ms', training_ready=False)
            if getattr(transport, 'collect_human', False):
                print(f'采集进度：等待第 {episode_number}/{episodes} 回合 Start；'
                      f'本次运行已完成 {completed_episodes} 回合，累计有效动作 {total_transitions} 条。', flush=True)
            started = transport.wait_start()
            transport.reset_history()
            episode = uuid.uuid4().hex
            audit = PeriodicAudit(actor.run, episode, config.replay_contract(), actor.version, training=training)
            known = {}
            verified = {'human': False, 'policy': False}
            fault = None
            last_receipt_time = time.monotonic()
            def receipt_hook(receipt):
                nonlocal fault, last_receipt_time
                if receipt.get('command_id') not in known:
                    return
                audit.submit('receipt', dict(receipt))
                expected_source, expected_wire = known[receipt['command_id']]
                last_receipt_time = time.monotonic()
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
            transport.receipt_hook = receipt_hook
            deadline = started+config.episode_seconds
            # StackObservations starts its 100ms reference lattice on the first
            # pump after reset. Sending on that same boundary can read the old
            # window when the pump runs a fraction of a millisecond early.
            # Leave time for the new window to be assembled before each send.
            phase_delay = .03 if getattr(transport, 'collect_human', False) else 0.
            schedule = PeriodicClock(time.monotonic() + phase_delay)
            used_stamp = None
            count = 0
            outcome = dict(episode=episode, policy_version=actor.version, success=False, reason='interrupted')
            last_owner = None
            try:
                actor.state('ACTIVE', control_mode='periodic_100ms', training_ready=False)
                if getattr(transport, 'collect_human', False):
                    print('ACTIVE: RB+摇杆控制；松开RB为零动作；308成功、307提前结束，否则到时停止。',
                          flush=True)
                    _banner('已开始采集：现在按住 RB 并推动摇杆控制机械臂', '36')
                    print('按 308 标记任务成功；按 307 提前结束；到时自动结束。\n', flush=True)
                while True:
                    transport._pump()
                    now = time.monotonic()
                    if not transport.connected:
                        raise RuntimeError('gamepad disconnected')
                    if fault:
                        raise RuntimeError(fault)
                    if now-last_receipt_time > 1.:
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
                    # Immediate stop on takeover; joystick command follows at the next tick.
                    if transport.pad.buttons.get(311, False) and last_owner == 'policy':
                        audit.submit('interrupt', transport.node.get_clock().now().nanoseconds)
                        transport.stop()
                        last_owner = None
                    timing = schedule.due(now)
                    if timing is None:
                        continue
                    selected_source = ('human' if getattr(transport, 'collect_human', False) or
                                       transport.pad.buttons.get(311, False) else 'policy')
                    action, source, gate, latest, used_stamp = choose_action(transport, used_stamp, verified[selected_source])
                    command_id = 'hil:'+uuid.uuid4().hex
                    transport.last_owner = source
                    transport.command_anchor_ns = latest[1] if latest is not None else None
                    wire = transport._publish(action, command_id)
                    known[command_id] = (source, wire)
                    last_owner = source
                    metadata = dict(command_id=command_id, action_source=source, gate=gate,
                        policy_version=actor.version, observation_present=latest is not None,
                        observation_reference_ns=transport.command_anchor_ns,
                        eef_receive_ns=getattr(transport, 'latest_eef_time', None),
                        command_send_ns=transport.node.get_clock().now().nanoseconds,
                        normalized_action=config.normalized_action(action).tolist(), wire_action=wire,
                        command_trace=dict(transport.last_command_trace), **timing)
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
                stop_ns = transport.node.get_clock().now().nanoseconds
                if training and transport.latest is not None:
                    boundary = (dict(observation_present=True, observation_reference_ns=transport.latest[1],
                                     eef_receive_ns=getattr(transport, 'latest_eef_time', None),
                                     command_send_ns=transport.node.get_clock().now().nanoseconds), transport.latest[0])
                transport.stop()
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
                # Stop first; callbacks may finish late. Never wait in the send loop.
                try:
                    drain_until = time.monotonic()+.3
                    while time.monotonic() < drain_until:
                        transport._pump()
                        # Success is terminal (no Q bootstrap). Capture its first
                        # real post-stop state before permitting ANY manual reset.
                        # The last command may be shortened by the explicit stop;
                        # this is recorded, never described as a full displacement.
                        if (training and outcome['success'] and transport.latest is not None and
                                getattr(transport, 'latest_eef_time', 0) > stop_ns and
                                (boundary is None or 'terminal_success_stop_ns' not in boundary[0])):
                            boundary = (dict(observation_present=True,
                                observation_reference_ns=transport.latest[1],
                                eef_receive_ns=transport.latest_eef_time,
                                terminal_success_stop_ns=stop_ns,
                                command_send_ns=transport.node.get_clock().now().nanoseconds), transport.latest[0])
                finally:
                    transport.receipt_hook = None
                    # No reset is permitted until the boundary is captured.
                    result = audit.finish(boundary, outcome, tick=transport.idle_tick)
                    actor.state('EPISODE_RECORDED', audit=result)
                    print('PERIODIC_SAVED: '+json.dumps(result), flush=True)
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
        actor.close_pipeline()
