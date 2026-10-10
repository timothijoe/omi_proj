"""Read-only transition sources for indexed replay; no expanded disk arrays."""
import json
from pathlib import Path

import numpy as np

from .transition_replay import CONTRACT_KEYS, _array


def periodic_records(directory, contract, validator, summary, *, reader=None):
    """Use the production periodic admission rules without rewriting the audit.

    IDs retain the original tick index. Gaps truncate the preceding transition;
    only the actual final accepted command can receive the success label.
    """
    from omi_hil_rl.hil.observation_storage import ObservationReader
    from omi_hil_rl.hil.periodic_replay import eligibility, timing_diagnostics
    from omi_hil_rl.real.sdk_action import output_action
    directory = Path(directory)
    audit = json.loads((directory/'audit.json').read_text())
    staging = json.loads((directory/'staging.json').read_text())
    if staging['contract'] != contract:
        raise ValueError('periodic source contract mismatch')
    summary.update(reason=audit['reason'], excluded={}, transitions=0)
    if audit['reason'] not in ('success', 'manual_stop', 'timeout'):
        summary['excluded']['abnormal_end'] = audit['ticks']
        return
    timing = audit.get('timing_policy', 'strict')
    if timing not in ('strict', 'diagnostic_only_v1'):
        raise ValueError('unknown periodic timing policy')
    paths = [directory/f'{i:06d}.npz' for i in range(audit['ticks'])]
    if len(list(directory.glob('[0-9]*.npz'))) != len(paths):
        raise ValueError('periodic source action count mismatch')
    ticks = []
    for path in paths:
        with np.load(path, allow_pickle=False) as z:
            ticks.append(json.loads(str(z['metadata'])))
    boundary_path = directory/'boundary.npz'
    if boundary_path.exists():
        with np.load(boundary_path, allow_pickle=False) as z:
            boundary = json.loads(str(z['metadata']))
    else:
        boundary = None
    receipts = [json.loads(line) for line in (directory/'receipts.jsonl').read_text().splitlines()]
    interruptions = json.loads((directory/'interruptions.json').read_text())
    following = ticks[1:] + [boundary] if ticks else []
    statuses = [eligibility(t, nxt, receipts, interruptions, timing_policy=timing)
                for t, nxt in zip(ticks, following)]
    reader = reader if reader is not None else ObservationReader(cache_size=0)

    def arrays(i):
        current = reader.read(paths[i])[1]
        nxt_path = paths[i+1] if i+1 < len(paths) else boundary_path
        return current, reader.read(nxt_path)[1], nxt_path

    # Match periodic_replay.convert's observation and wire validation before
    # deciding boundaries. A bad middle sample must split, not join, a trajectory.
    for i, status in enumerate(statuses):
        if status != 'valid':
            continue
        try:
            obs, nxt, _ = arrays(i)
            for values in (obs, nxt):
                if set(values) != set(validator.buffer.observation_space.spaces):
                    raise ValueError('observation keys')
                for key, space in validator.buffer.observation_space.spaces.items():
                    _array(values[key], space, key)
                if (timing == 'strict' and not values['history_mask'].all()) or np.any(values['state'][:, :7]):
                    raise ValueError('incomplete history or joints')
                cams = values['camera_mask'] if timing == 'strict' else values['camera_mask'][-1:]
                if not cams[:, 0].all() or (contract['config']['wrist_camera'] == 'required' and not cams[:, 1].all()):
                    raise ValueError('missing camera')
            action = _array(ticks[i]['normalized_action'], validator.buffer.action_space, 'action')
            wire = output_action(action.astype(np.float64)*np.asarray(contract['physical_action_scale']),
                                 contract['config']['sdk_convention'])
            if not np.allclose(wire, ticks[i]['wire_action'], rtol=1e-6, atol=1e-8):
                raise ValueError('wire/action mismatch')
        except (ValueError, KeyError, TypeError):
            statuses[i] = 'invalid_observation_or_action'
    for i, status in enumerate(statuses):
        if status != 'valid':
            summary['excluded'][status] = summary['excluded'].get(status, 0)+1
            continue
        tick, nxt_meta = ticks[i], following[i]
        final = i+1 == len(ticks) or statuses[i+1] != 'valid'
        success = bool(final and i+1 == len(ticks) and audit['success'])
        obs, nxt, nxt_path = arrays(i)
        record = {k: contract[k] for k in CONTRACT_KEYS}
        record.update(episode=directory.name, step=i, observation=obs, next_observation=nxt,
            executed_action=np.asarray(tick['normalized_action'], np.float32), reward=float(success),
            terminated=success, truncated=bool(final and not success), episode_success=bool(audit['success']),
            observation_time_ns=tick['observation_reference_ns'],
            next_observation_time_ns=nxt_meta['observation_reference_ns'],
            action_source=tick['action_source'], command_status='periodic_accepted_command',
            policy_version=audit['policy_version'],
            command_audit=dict(source_episode=directory.name, periodic_tick=i,
                arbitration_mode=tick.get('arbitration_mode', 'immediate'), arbitration=tick.get('arbitration'),
                timing_policy=timing, timing_diagnostics=timing_diagnostics(tick, nxt_meta, receipts, interruptions),
                next_eef_receive_ns=nxt_meta.get('eef_receive_ns'),
                terminal_success_stop_ns=nxt_meta.get('terminal_success_stop_ns'),
                command_id=tick['command_id'], command_trace=tick['command_trace'],
                receipts=[r for r in receipts if r.get('command_id') == tick['command_id']],
                semantics='accepted_command_not_measured_displacement'))
        summary['transitions'] += 1
        yield paths[i], nxt_path, record
