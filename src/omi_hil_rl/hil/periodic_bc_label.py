"""BC-only validation of human labels exported by periodic collection.

This module is used by imitation-learning data readers. It does not change
the general transition, replay, or robot command validators.
"""
import numpy as np

from .demo import validate_command_label


def validate_bc_label(contract, action, metadata):
    if metadata.get('command_status') != 'periodic_accepted_command':
        return validate_command_label(contract, action, metadata)
    from omi_hil_rl.real.sdk_action import output_action
    try:
        audit = metadata['command_audit']
        trace, receipts = audit['command_trace'], audit['receipts']
        command_id = audit['command_id']
        start, end = metadata['observation_time_ns'], metadata['next_observation_time_ns']
        send = trace['command_send_ns']
        if (audit['semantics'] != 'accepted_command_not_measured_displacement' or
                not metadata['episode'].startswith(audit['source_episode']+'-segment-') or
                not isinstance(audit['periodic_tick'], int) or audit['periodic_tick'] < 0 or
                not command_id or command_id != trace['command_id'] or
                metadata['action_source'] != 'human' or trace['action_source'] != 'human' or
                not trace['label_candidate'] or trace['execution_confirmed'] is not False):
            raise ValueError('periodic human command identity/semantics mismatch')
        if (not 80_000_000 <= end-start <= 150_000_000 or
                not start <= send < end or send-start > 100_000_000 or
                trace['observation_reference_ns'] != start or
                trace['action_contract'] != contract['action_contract'] or
                trace['output_convention'] != contract['config']['sdk_convention']):
            raise ValueError('periodic command timing/contract mismatch')
        if not np.array_equal(np.asarray(trace['normalized_action'], np.float32), action):
            raise ValueError('periodic normalized action mismatch')
        physical = np.asarray(action, np.float64)*np.asarray(contract['physical_action_scale'], np.float64)
        if (not np.allclose(trace['action_m_rad'], physical, atol=1e-9, rtol=1e-6) or
                not np.allclose(trace['wire_action'], output_action(physical, trace['output_convention']),
                                atol=1e-8, rtol=1e-6)):
            raise ValueError('periodic physical/wire action mismatch')
        accepted = [r for r in receipts if r['accepted'] and
                    r['status'] in ('queue_accepted', 'velocity_zero_stopped')]
        if not accepted:
            raise ValueError('periodic command has no acceptance receipt')
        receipt = accepted[0]
        stamp = receipt['timestamp_ns']
        if (not send <= stamp < end or stamp-send > 50_000_000 or
                not stamp < audit['next_eef_receive_ns'] <= end):
            raise ValueError('periodic receipt/EEF is not causal')
        for item in receipts:
            if (item['command_id'] != command_id or item['arm'] != 'A' or
                    item['delta_frame'] != 'base' or item['control_mode'] != 'velocity_hold' or
                    item['action_source'] != 'human' or
                    abs(float(item['nominal_duration_s'])-.1) > .001 or
                    not np.allclose(item['wire_action'], trace['wire_action'], atol=1e-9, rtol=1e-9)):
                raise ValueError('periodic receipt contract mismatch')
            if (item['timestamp_ns'] < end and
                    (not item['accepted'] or item['status'] not in
                     ('queue_accepted', 'velocity_zero_stopped', 'velocity_window_sent'))):
                raise ValueError('periodic command rejected during observation interval')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('missing periodic command label/receipt evidence') from exc
