"""Causal BC pairs from passive bags: recorded commands, never RL receipts.

Observations stay on the deployed 100ms lattice. The one command in the next
100ms is the label; no future observation or successful-episode claim is needed.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from torch.utils.data import Dataset

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.demo import save_npz
from omi_hil_rl.hil.exchange import atomic_json
from omi_hil_rl.real.sdk_action import output_action
from .demo_wrench import read_wrenches, align_history, MAX_AGE_NS
from .eef_bc_data import sha256
from .eef_bc_grid import GridProfile
from .passive_preview import commands_between, PERIOD
from .sensor_alignment import AuditedObservations, read_sensor_metadata, prefer_record_topic, add_wrench_alignment
from .transition_replay import _array, _box

VERSION = 'omi-passive-command-bc-wrench-v1'
PLAN_VERSION = 'omi-passive-command-bc-plan-v1'
Q = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])


def inverse_wire(wire, convention):
    wire = np.asarray(wire, np.float64)
    if wire.shape != (6,) or not np.isfinite(wire).all():
        raise ValueError('expected six finite wire values')
    if convention not in ('sdk-x-forward-z-left', 'sdk-base-aligned'):
        raise ValueError('explicit SDK ABC publisher convention required')
    translation = wire[:3] / 1000.
    rotation = Rotation.from_euler('xyz', wire[3:], degrees=True).as_rotvec()
    if convention == 'sdk-x-forward-z-left':
        translation, rotation = Q.T @ translation, Q.T @ rotation
    physical = np.r_[translation, rotation]
    if not np.allclose(output_action(physical, convention), wire, rtol=1e-7, atol=1e-7):
        raise ValueError('wire -> policy -> wire roundtrip mismatch')
    return physical


def contract_for(provenance):
    if provenance['rate_hz'] != 10:
        raise ValueError('10 Hz command provenance required')
    config = HILConfig(transport='ros', wrist_camera='required',
        translation_step_m=provenance['effective_translation_mm_s'] / 10000.,
        rotation_step_rad=math.radians(provenance['effective_rotation_deg_s']) / 10.,
        sdk_convention=provenance['output_convention'])
    contract = config.replay_contract()
    contract.update(observation_contract='passive-nojoint-current9stack-dual-wrench-v1',
        action_contract='passive-recorded-policy-base-m-rotvec-normalized-v1',
        action_semantics='recorded_command_not_execution_confirmed', reward_contract='none_bc_only',
        wrench=dict(shape=[10, 2, 6], sides=['a', 'b'], components=['Fx', 'Fy', 'Fz', 'Tx', 'Ty', 'Tz'],
                    units='uncalibrated_sdk', max_receive_age_ns=MAX_AGE_NS, training_input=True))
    contract['observations'].update(
        wrench=dict(shape=[10, 2, 6], dtype='float32', low=-1e30, high=1e30),
        wrench_mask=dict(shape=[10, 2], dtype='uint8', low=0, high=1))
    return contract


def convert_session(session, output, provenance, contract, exclusions=(), max_tactile_skew_ms=None):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    session, output = Path(session).resolve(), Path(output)
    settings = json.loads((session / 'session.json').read_text())
    topic, bag = settings['command_topic'], session / 'raw'
    if topic != provenance['command_topic']:
        raise ValueError('publisher provenance and bag command topic disagree')
    def reader_for(topics):
        reader = rosbag2_py.SequentialReader()
        reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id=''), rosbag2_py.ConverterOptions('', ''))
        reader.set_filter(rosbag2_py.StorageFilter(topics=topics))
        return reader
    reader = reader_for([topic])
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    if types.get(topic) != 'std_msgs/msg/Float64MultiArray':
        raise ValueError('missing recorded command topic')
    command_class = get_message(types[topic])
    commands = []
    while reader.has_next():
        _, payload, receive = reader.read_next()
        wire = np.asarray(deserialize_message(payload, command_class).data, np.float64)
        physical = inverse_wire(wire, provenance['output_convention'])
        commands.append(dict(bag_receive_ns=int(receive), wire_action=wire.tolist(), physical=physical))
    if not commands:
        raise ValueError('no command labels')
    commands.sort(key=lambda row: row['bag_receive_ns'])
    del reader
    wrenches = read_wrenches(bag)
    runtime = AuditedObservations(GridProfile('required').CONTRACT, 'strict', 'raw',
        provenance=read_sensor_metadata(bag), max_tactile_skew_ms=max_tactile_skew_ms)
    prefer_record_topic(runtime, types)
    reader = reader_for(list(runtime.topics))
    classes = {t: get_message(types[t]) for t in runtime.topics if t in types}
    if set(classes) != set(runtime.topics):
        raise ValueError('required observation topic missing')
    directory = output / 'episodes' / session.name
    directory.mkdir(parents=True, exist_ok=False)
    scale = np.asarray(contract['physical_action_scale'], np.float64)
    count, nonzero, segment = 0, 0, -1
    next_ref, first, last, previous_saved = None, None, None, None
    reasons, rows = Counter(), []
    def sample(reference):
        nonlocal count, nonzero, segment, previous_saved
        window, audit = runtime.window(reference)
        if window is None or not window[1].all():
            reasons[audit['reason'] if window is None else 'history_warmup_or_gap'] += 1
            return
        candidates = commands_between(commands, reference, reference + PERIOD)
        if len(candidates) != 1:
            reasons['no_command' if not candidates else 'multiple_commands'] += 1
            return
        command = candidates[0]
        relative = (command['bag_receive_ns'] - first) / 1e9
        if any(start <= relative < end for start, end in exclusions):
            reasons['operator_excluded_interval'] += 1
            return
        physical = command['physical']
        if (np.linalg.norm(physical[:3]) > scale[0] + 1e-9 or
                np.linalg.norm(physical[3:]) > scale[3] + 1e-8):
            reasons['exceeds_confirmed_manual_speed'] += 1
            return
        action = (physical / scale).astype(np.float32)
        if np.any(np.abs(action) > 1.000001):
            raise ValueError('action outside configured normalization')
        action = np.clip(action, -1, 1)
        data, mask = window
        observation = dict(data, history_mask=mask.astype(np.uint8))
        aligned, frames = align_history(wrenches, reference)
        add_wrench_alignment(audit, aligned, runtime.provenance, reference)
        if not aligned['wrench_mask'].all():
            reasons['incomplete_wrench_history'] += 1
            return
        observation.update(wrench=aligned['wrench'], wrench_mask=aligned['wrench_mask'])
        if previous_saved is None or reference - previous_saved != PERIOD:
            segment += 1
        metadata = dict(episode=session.name, step=count, segment=segment,
            observation_time_ns=reference, command_receive_ns=command['bag_receive_ns'],
            command_delay_ns=command['bag_receive_ns'] - reference, wire_action=command['wire_action'],
            action_m_rad=physical.tolist(), action_semantics=contract['action_semantics'],
            observation_audit=audit, wrench_frame_ids=frames,
            success=None, sender_mode=provenance.get('home_usage', 'unknown'))
        arrays = {'observation__' + k: v for k, v in observation.items()}
        arrays.update(action=action, recorded_wire_action=np.asarray(command['wire_action'], np.float64),
                      wrench_receive_ns=aligned['wrench_receive_ns'], wrench_header_ns=aligned['wrench_header_ns'],
                      metadata=np.asarray(json.dumps(metadata)))
        save_npz(directory / f'{count:06d}.npz', arrays)
        rows.append(dict(step=count, segment=segment, reference_ns=reference,
                         command_receive_ns=command['bag_receive_ns'], nonzero=bool(np.any(action))))
        count += 1
        nonzero += int(np.any(action))
        previous_saved = reference
    while reader.has_next():
        tpc, payload, receive = reader.read_next()
        if first is None:
            first = next_ref = receive
        while next_ref < receive:
            sample(next_ref)
            next_ref += PERIOD
        runtime.ingest(runtime.topics[tpc], deserialize_message(payload, classes[tpc]), receive)
        last = receive
    if last is not None and next_ref == last:
        sample(next_ref)
    if not count:
        raise ValueError('no usable samples: ' + json.dumps(dict(reasons)))
    manifest = dict(version=VERSION, episode=session.name, count=count, nonzero=nonzero,
        segments=segment + 1, contract=contract, source_bag=str(bag),
        source_files={p.name: sha256(p) for p in sorted(bag.iterdir()) if p.is_file()},
        publisher_provenance=provenance, excluded=dict(reasons), ingress_rejections=dict(runtime.rejected),
        source_command_count=len(commands), source_wrench_count={s: len(r) for s, r in wrenches.items()},
        alignment='strict 100ms observation lattice -> single recorded command in [reference, reference+100ms)',
        max_tactile_host_header_skew_ms=max_tactile_skew_ms,
        reward_used=False, success_annotation=None, sample_index=rows,
        limitations=['recorder timestamp pairing is not sender input timing or physical execution proof',
                     'gaps are independent BC samples, never stitched RL transitions',
                     'wrench device freshness/physical units unverified'])
    atomic_json(directory / 'dataset.json', manifest)
    print(json.dumps(dict(episode=session.name, samples=count, nonzero=nonzero,
                         excluded=dict(reasons), segments=segment + 1)), flush=True)
    return manifest


def make_plan(root, validation_session):
    root = Path(root).resolve()
    paths = sorted(root.glob('episodes/*/dataset.json'))
    episodes, contract = [], None
    for path in paths:
        manifest = json.loads(path.read_text())
        if manifest['version'] != VERSION:
            raise ValueError('unsupported passive BC dataset')
        if contract is not None and contract != manifest['contract']:
            raise ValueError('mixed contracts')
        contract = manifest['contract']
        episodes.append(dict(episode=manifest['episode'], count=manifest['count'], path=str(path.parent),
            manifest_sha256=sha256(path), samples_sha256=[sha256(path.parent / f'{i:06d}.npz') for i in range(manifest['count'])]))
    training = [ep for ep in episodes if ep['episode'] != validation_session]
    validation = [ep for ep in episodes if ep['episode'] == validation_session]
    if not training or len(validation) != 1:
        raise ValueError('one complete validation bag and at least one training bag required')
    plan = dict(version=PLAN_VERSION, contract=contract, training=training, validation=validation,
                target='recorded_command_bc_not_confirmed_execution', reward_used=False,
                split='whole bag held out; no overlapping frames across train/validation')
    atomic_json(root / 'plan.json', plan)
    return plan


class PassiveDataset(Dataset):
    def __init__(self, plan, split):
        if plan['version'] != PLAN_VERSION or split not in ('training', 'validation'):
            raise ValueError('invalid passive BC plan')
        self.contract = plan['contract']
        if self.contract['action_semantics'] != 'recorded_command_not_execution_confirmed':
            raise ValueError('passive labels cannot become accepted-command receipts')
        if ({e['episode'] for e in plan['training']} & {e['episode'] for e in plan['validation']} or
                {e['path'] for e in plan['training']} & {e['path'] for e in plan['validation']}):
            raise ValueError('training/validation bag leakage')
        self.index = []
        specs = {k: _box(v) for k, v in self.contract['observations'].items()}
        action_space = _box(self.contract['action'])
        for ep in plan[split]:
            path = Path(ep['path'])
            if (path.parent.parent / 'conversion_pending.json').exists():
                raise ValueError('dataset conversion incomplete')
            if sha256(path / 'dataset.json') != ep['manifest_sha256']:
                raise ValueError('manifest hash mismatch')
            manifest = json.loads((path / 'dataset.json').read_text())
            if manifest['version'] != VERSION or manifest['contract'] != self.contract or manifest['count'] != ep['count']:
                raise ValueError('manifest does not match plan')
            if len(ep['samples_sha256']) != ep['count']:
                raise ValueError('sample count mismatch')
            previous = None
            for i, digest in enumerate(ep['samples_sha256']):
                sample = path / f'{i:06d}.npz'
                if sha256(sample) != digest:
                    raise ValueError('sample hash mismatch')
                obs, action, metadata = self.read(sample)
                if set(obs) != set(specs):
                    raise ValueError('observation keys mismatch')
                for key, space in specs.items():
                    _array(obs[key], space, key)
                _array(action, action_space, 'action')
                reference, command = metadata['observation_time_ns'], metadata['command_receive_ns']
                if not 0 <= command - reference < PERIOD or (previous is not None and reference <= previous):
                    raise ValueError('noncausal or nonmonotonic BC sample')
                if (not obs['history_mask'].all() or not obs['wrench_mask'].all() or
                        not obs['camera_mask'].all() or np.any(obs['state'][:, :7])):
                    raise ValueError('incomplete history or joints enabled')
                with np.load(sample, allow_pickle=False) as archive:
                    slot_times = reference - np.arange(9, -1, -1, dtype=np.int64)[:, None] * PERIOD
                    age = slot_times - archive['wrench_receive_ns']
                    if np.any(age < 0) or np.any(age > MAX_AGE_NS):
                        raise ValueError('noncausal or stale wrench alignment')
                    if not np.array_equal(archive['recorded_wire_action'], metadata['wire_action']):
                        raise ValueError('raw wire metadata mismatch')
                expected = inverse_wire(metadata['wire_action'], self.contract['config']['sdk_convention'])
                if not np.allclose(action * self.contract['physical_action_scale'], expected, atol=1e-9, rtol=1e-6):
                    raise ValueError('wire/action label mismatch')
                previous = reference
                self.index.append(sample)
        if not self.index:
            raise ValueError('empty training/validation split')

    @staticmethod
    def read(path):
        with np.load(path, allow_pickle=False) as archive:
            obs = {k[13:]: archive[k].copy() for k in archive.files if k.startswith('observation__')}
            return obs, archive['action'].copy(), json.loads(str(archive['metadata']))

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        obs, action, _ = self.read(self.index[index])
        return obs, action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions', nargs='+', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validation-session', required=True)
    parser.add_argument('--exclusions', type=Path, help='JSON: session -> excluded [start,end) seconds since first sensor')
    parser.add_argument('--max-tactile-skew-ms', type=float, help='optional host-header skew bound')
    args = parser.parse_args()
    provenance = json.loads(args.provenance.read_text())
    contract = contract_for(provenance)
    exclusions = {} if args.exclusions is None else json.loads(args.exclusions.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    atomic_json(args.output / 'conversion_pending.json', dict(sessions=[str(p.resolve()) for p in args.sessions]))
    reports = [convert_session(p, args.output, provenance, contract, exclusions.get(p.name, ()),
                              args.max_tactile_skew_ms) for p in args.sessions]
    plan = make_plan(args.output, args.validation_session)
    atomic_json(args.output / 'report.json', dict(version=VERSION, episodes=reports,
        training_samples=sum(ep['count'] for ep in plan['training']),
        validation_samples=sum(ep['count'] for ep in plan['validation']), reward_used=False))
    (args.output / 'conversion_pending.json').unlink()
    print('BC dataset ready: ' + str(args.output / 'plan.json'), flush=True)


if __name__ == '__main__':
    main()
