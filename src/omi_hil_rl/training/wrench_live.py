"""Strict passive-BC checkpoint adapter and causal live wrench history."""
from collections import deque
import time

import numpy as np
import torch

from .stack_shadow import StackObservations
from .demo_wrench import TOPICS, MAX_AGE_NS, align_history
from .eef_bc_grid import GridProfile
from omi_hil_rl.hil.networks import load_actor
from omi_hil_rl.real.ros_topics import wrench_value


def load_wrench_policy(path, device):
    # Validate the full training contract before constructing any ROS publisher.
    from .passive_bc import contract_for
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    contract, recipe = checkpoint['contract'], checkpoint['recipe']
    expected = contract_for(dict(rate_hz=10, effective_translation_mm_s=5,
        effective_rotation_deg_s=5, output_convention='sdk-x-forward-z-left'))
    if (contract != expected or recipe.get('encoder') != 'current9stack'
            or recipe.get('wrench_history') is not True
            or recipe.get('base_contract') != GridProfile('required').CONTRACT
            or recipe.get('sdk_convention') != 'sdk-x-forward-z-left'
            or recipe.get('wrench_contract') != expected['wrench']
            or recipe.get('action_semantics') != expected['action_semantics']
            or checkpoint.get('algorithm') != 'omi-human-demo-bc-v1'):
        raise ValueError('unsupported live passive wrench BC checkpoint contract')
    actor, step, recipe = load_actor(path, expected, device)
    # Shared live runner uses the base sensor contract for experimental bounds.
    actor.contract = recipe['base_contract']
    actor.physical_action_scale = np.asarray(expected['physical_action_scale'], np.float32)
    metadata = dict(checkpoint, config={'version': expected['observation_contract']}, step=step)
    return actor, recipe['normalization'], metadata


class WrenchObservations(StackObservations):
    def __init__(self, contract, header_mode='strict', eef_reference='raw'):
        if header_mode != 'strict' or eef_reference != 'raw':
            raise ValueError('wrench BC requires strict headers and raw EEF, matching training')
        super().__init__(contract, header_mode, eef_reference)
        self.topics.update({t: 'wrench_' + side for t, side in TOPICS.items()})

    def reset(self):
        super().reset()
        self.wrenches = {side: deque(maxlen=4096) for side in 'ab'}

    def ingest(self, key, msg, receive_ns):
        if not key.startswith('wrench_'):
            return super().ingest(key, msg, receive_ns)
        if self.last_receive is not None and receive_ns < self.last_receive:
            self.reset()
        self.last_receive = receive_ns
        self.counts[key] += 1
        side = key.removeprefix('wrench_')
        stamp, frame = 0, ''
        try:
            stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            frame = msg.header.frame_id
            value = wrench_value(msg)
            if frame != 'tactile_' + side:
                raise ValueError('wrench_frame')
            if not -self.contract['ingress_max_header_ahead_ns'] <= receive_ns-stamp <= MAX_AGE_NS:
                raise ValueError('wrench_header_age')
        except (ValueError, AttributeError, TypeError) as exc:
            # Invalid newest sample must not silently fall back to an older valid value.
            value = np.full(6, np.nan, np.float32)
            self.rejected[key + ':' + str(exc)] += 1
            self.latest[key] = dict(receive_ns=receive_ns, accepted=False, reason=str(exc))
            accepted = False
        else:
            self.accepted[key] += 1
            self.latest[key] = dict(receive_ns=receive_ns, accepted=True, header_ns=stamp)
            accepted = True
        self.wrenches[side].append((receive_ns, stamp, value, frame))
        while self.wrenches[side] and receive_ns-self.wrenches[side][0][0] > 2_000_000_000:
            self.wrenches[side].popleft()
        return accepted

    def window(self, reference_ns):
        window, status = super().window(reference_ns)
        aligned, frames = align_history(self.wrenches, reference_ns)
        status.update(wrench_mask=aligned['wrench_mask'].tolist(),
            wrench_receive_ns=aligned['wrench_receive_ns'].tolist(),
            wrench_header_ns=aligned['wrench_header_ns'].tolist(), wrench_frame_ids=frames)
        healthy = aligned['wrench_mask'].all() and all(
            self.latest.get('wrench_' + side, {}).get('accepted', False) for side in 'ab')
        if not healthy:
            status['reason'] = 'incomplete_or_invalid_wrench_history'
            return None, status
        if window is not None:
            data, mask = window
            data.update(wrench=aligned['wrench'], wrench_mask=aligned['wrench_mask'])
        return window, status


def infer_wrench_window(model, norm, window, device):
    data, mask = window
    if device.type == 'cuda':
        torch.cuda.synchronize()
    started = time.perf_counter_ns()
    obs = dict(data, history_mask=mask.astype(np.uint8))
    with torch.inference_mode():
        tensor = {k: torch.as_tensor(v, device=device)[None] for k, v in obs.items()}
        normalized = model.sample(tensor, deterministic=True)[0].cpu().numpy()[0]
    if normalized.shape != (6,) or not np.isfinite(normalized).all() or np.any(np.abs(normalized) > 1):
        raise ValueError('invalid normalized BC action')
    action = normalized * model.physical_action_scale
    return action, (time.perf_counter_ns()-started)/1e6
