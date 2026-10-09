"""Conservative, post-episode conversion of periodic accepted-command samples.

Labels remain normalized commands, NOT measured displacement. Missing intervals
split trajectories; truncation bootstraps at gaps and never invents a success.
"""
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .exchange import EpisodeSpool
from omi_hil_rl.training.transition_replay import _spaces, _array


def timing_diagnostics(tick, following, receipts, interruptions):
    """Timing evidence, independent of whether an accepted command is trainable."""
    if following is None or not tick['observation_present'] or not following['observation_present']:
        return []
    start, end, send = tick['observation_reference_ns'], following['observation_reference_ns'], tick['command_send_ns']
    reasons = []
    if not start <= send < end <= following['command_send_ns']:
        reasons.append('noncausal')
    if not 80_000_000 <= end-start <= 150_000_000 or send-start > 100_000_000:
        reasons.append('timing_gap')
    if any(send <= t <= max(end, send) for t in interruptions):
        reasons.append('interrupted_command')
    accepted = [r for r in receipts if r.get('command_id') == tick['command_id'] and r.get('accepted')
                and r.get('status') in ('queue_accepted', 'velocity_zero_stopped')]
    if accepted:
        receipt = accepted[0]
        stamp = receipt.get('timestamp_ns', -1)
        if not send <= stamp < end:
            reasons.append('acceptance_outside_interval')
        if stamp-send > 50_000_000:
            reasons.append('acceptance_too_late')
        eef = following.get('eef_receive_ns')
        if eef is None or not stamp < eef <= end:
            reasons.append('missing_causal_eef')
        stop = following.get('terminal_success_stop_ns')
        if stop is not None and not stamp < stop <= end:
            reasons.append('terminal_stop_before_acceptance')
    return reasons


def eligibility(tick, following, receipts, interruptions, *, timing_policy='strict'):
    if following is None or not tick['observation_present'] or not following['observation_present']:
        return 'missing_observation'
    start, end = tick['observation_reference_ns'], following['observation_reference_ns']
    send = tick['command_send_ns']
    diagnostic = timing_policy == 'diagnostic_only_v1'
    if not diagnostic and not start <= send < end <= following['command_send_ns']:
        return 'noncausal'
    # Legacy recordings retain their original fixed-interval admission rule.
    if not diagnostic and (not 80_000_000 <= end-start <= 150_000_000 or send-start > 100_000_000):
        return 'timing_gap'
    if not diagnostic and any(send <= t <= end for t in interruptions):
        return 'interrupted_command'
    if tick['gate'] not in ('human', 'policy'):
        return 'no_action_candidate'
    matches = [r for r in receipts if r.get('command_id') == tick['command_id']]
    adopted = [r for r in matches if r.get('accepted') and
               r.get('status') in ('queue_accepted', 'velocity_zero_stopped')]
    if not adopted:
        return 'missing_acceptance'
    receipt = adopted[0]
    duration = float(receipt.get('nominal_duration_s', 0))
    if (receipt.get('wire_action') != tick['wire_action'] or receipt.get('arm') != 'A' or
            receipt.get('delta_frame') != 'base' or receipt.get('control_mode') != 'velocity_hold' or
            receipt.get('action_source') != tick['action_source'] or
            not np.isfinite(duration) or abs(duration-.1) > .001):
        return 'receipt_contract'
    if not diagnostic and not send <= receipt.get('timestamp_ns', -1) < end:
        return 'acceptance_outside_interval'
    if not diagnostic and receipt['timestamp_ns']-send > 50_000_000:
        return 'acceptance_too_late'
    stop = following.get('terminal_success_stop_ns')
    if not diagnostic and stop is not None and not receipt['timestamp_ns'] < stop <= end:
        return 'terminal_stop_before_acceptance'
    eef = following.get('eef_receive_ns')
    if not diagnostic and (eef is None or not receipt['timestamp_ns'] < eef <= end):
        return 'missing_causal_eef'
    for r in matches:
        if diagnostic and r.get('status') in ('queue_replaced', 'queue_cancelled'):
            continue  # Actual accepted command was shortened; retain its recorded duration/status.
        expected_terminal_stop = (stop is not None and r.get('accepted') and r.get('status') == 'queue_cancelled'
                                  and stop <= r.get('timestamp_ns', 0) <= end)
        if (not expected_terminal_stop and (not r.get('accepted') or r.get('status') not in
                ('queue_accepted', 'velocity_zero_stopped', 'velocity_window_sent'))
                and r.get('timestamp_ns', 0) < end):
            return 'receiver_rejected_interval'
    return 'valid'


def convert(directory, run, contract, version, ticks, receipts, interruptions, boundary, outcome, *, timing_policy='strict', frame_writer=None):
    """Called in the disk writer thread. Only complete normal outcomes may enter replay."""
    if outcome['reason'] not in ('success', 'manual_stop', 'timeout'):
        return dict(training_ready=False, transitions=0, segments=[], excluded={'abnormal_end': len(ticks)})
    boundary_meta = boundary[0] if boundary else None
    statuses = [eligibility(t, ticks[i+1] if i+1 < len(ticks) else boundary_meta, receipts, interruptions,
                            timing_policy=timing_policy)
                for i, t in enumerate(ticks)]
    diagnostics = [timing_diagnostics(t, ticks[i+1] if i+1 < len(ticks) else boundary_meta, receipts, interruptions)
                   for i, t in enumerate(ticks)]
    from .exchange import atomic_json
    atomic_json(Path(directory)/'timing_diagnostics.json', diagnostics)
    spool, segments, count = None, [], 0
    from .observation_storage import ObservationReader
    reader = ObservationReader()

    def observation(index):
        if index == len(ticks):
            return boundary[1]
        return reader.read(Path(directory)/f'{index:06d}.npz')[1]

    spaces, action_space = _spaces(contract)
    # Validate before exposing ANY segment; malformed input remains audit-only.
    for i, status in enumerate(statuses):
        if status != 'valid':
            continue
        try:
            for obs in (observation(i), observation(i+1)):
                if set(obs) != set(spaces.spaces):
                    raise ValueError('observation keys')
                for key, space in spaces.spaces.items():
                    _array(obs[key], space, key)
                if (timing_policy == 'strict' and not obs['history_mask'].all()) or np.any(obs['state'][:, :7]):
                    raise ValueError('incomplete history or joints')
                cameras = obs['camera_mask'] if timing_policy == 'strict' else obs['camera_mask'][-1:]
                if not cameras[:, 0].all() or (contract['config']['wrist_camera'] == 'required'
                                              and not cameras[:, 1].all()):
                    raise ValueError('missing camera')
            action = _array(ticks[i]['normalized_action'], action_space, 'action')
            from omi_hil_rl.real.sdk_action import output_action
            wire = output_action(action.astype(np.float64)*np.asarray(contract['physical_action_scale']),
                                 contract['config']['sdk_convention'])
            if not np.allclose(wire, ticks[i]['wire_action'], rtol=1e-6, atol=1e-8):
                raise ValueError('wire/action mismatch')
        except (ValueError, KeyError, TypeError):
            statuses[i] = 'invalid_observation_or_action'

    for i, status in enumerate(statuses):
        if status != 'valid':
            continue
        if spool is None:
            name = outcome['episode'] + f'-segment-{i:06d}'
            spool = EpisodeSpool(run, name, contract, policy_version=version, frame_writer=frame_writer)
        tick = ticks[i]
        following = ticks[i+1] if i+1 < len(ticks) else boundary_meta
        final = i+1 == len(ticks) or statuses[i+1] != 'valid'
        success = bool(final and i+1 == len(ticks) and outcome['success'])
        spool.append(observation(i), observation(i+1), float(success), success, final and not success,
            dict(episode=spool.episode, step=spool.count, executed_action=np.asarray(tick['normalized_action'], np.float32),
                 observation_time_ns=tick['observation_reference_ns'],
                 next_observation_time_ns=following['observation_reference_ns'],
                 action_source=tick['action_source'], command_status='periodic_accepted_command',
                 command_audit=dict(source_episode=outcome['episode'], periodic_tick=i,
                    arbitration_mode=tick.get('arbitration_mode', 'immediate'),
                    arbitration=tick.get('arbitration'),
                    timing_policy=timing_policy, timing_diagnostics=diagnostics[i],
                    next_eef_receive_ns=following.get('eef_receive_ns'),
                    terminal_success_stop_ns=following.get('terminal_success_stop_ns'),
                    command_id=tick['command_id'], command_trace=tick['command_trace'],
                    receipts=[r for r in receipts if r.get('command_id') == tick['command_id']],
                    semantics='accepted_command_not_measured_displacement')))
        count += 1
        if final:
            spool.finish(True, reason=outcome['reason'] if i+1 == len(ticks) else 'periodic_data_gap')
            segments.append(spool.episode)
            spool = None
    return dict(training_ready=bool(count), transitions=count, segments=segments,
                timing_diagnostics=dict(Counter(reason for row in diagnostics for reason in row)),
                excluded=dict(Counter(s for s in statuses if s != 'valid')),
                success_label_recorded=bool(statuses and statuses[-1] == 'valid' and outcome['success']))
