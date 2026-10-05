"""Self-contained demo bag snapshots and offline, command-free dataset extraction."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from .exchange import atomic_json

SAMPLE_TOPIC = '/omi/demo/sample'
SAMPLE_VERSION = 'omi-demo-snapshot-v1'


def encode_sample(episode, step, path):
    payload = Path(path).read_bytes()
    return dict(version=SAMPLE_VERSION, episode=episode, step=step,
                sha256=hashlib.sha256(payload).hexdigest(), npz_base64=base64.b64encode(payload).decode('ascii'))


def safe_episode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('invalid episode ID')
    return value


def bag_records(path):
    """Read sqlite3/MCAP locally; never publish or replay robot topics."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from std_msgs.msg import String
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(Path(path).resolve()), storage_id=''),
                rosbag2_py.ConverterOptions('', ''))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    for topic in (SAMPLE_TOPIC, '/omi/demo/event'):
        if types.get(topic) != 'std_msgs/msg/String':
            raise ValueError(f'Bag lacks {topic} String. Use the new record_demo_bag.sh collector; legacy bags cannot recover exact model windows.')
    reader.set_filter(rosbag2_py.StorageFilter(topics=[SAMPLE_TOPIC, '/omi/demo/event']))
    while reader.has_next():
        topic, payload, stamp = reader.read_next()
        yield topic, json.loads(deserialize_message(payload, String).data), stamp


def convert_records(records, output, *, source):
    """Stream snapshots to disk, then publish manifests only after complete validation."""
    from .demo import DEMO_VERSION, read_demo_step
    from .config import HILConfig
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / 'conversion_pending.json', dict(source=str(source)))
    seen, ends, sessions = {}, {}, []
    for topic, value, stamp in records:
        if topic == SAMPLE_TOPIC:
            if value.get('version') != SAMPLE_VERSION:
                raise ValueError('unsupported snapshot version')
            ep, step = safe_episode(value['episode']), value['step']
            if type(step) is not int or not 0 <= step < 1_000_000:
                raise ValueError('invalid sample step')
            payload = base64.b64decode(value['npz_base64'], validate=True)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != value['sha256']:
                raise ValueError('snapshot hash mismatch')
            entries = seen.setdefault(ep, {})
            if step in entries:
                if entries[step] != digest:
                    raise ValueError('conflicting duplicate sample')
                continue
            entries[step] = digest
            directory = output / 'episodes' / ep
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f'{step:06d}.npz').write_bytes(payload)
        elif topic == '/omi/demo/event':
            if value.get('kind') == 'session_start':
                sessions.append(value)
            elif value.get('kind') == 'episode_end':
                ep = safe_episode(value['episode'])
                if ep in ends and ends[ep] != value:
                    raise ValueError('conflicting episode end')
                ends[ep] = value
    pending_manifests = []
    for ep, end in ends.items():
        if not end.get('keep') or not end.get('valid'):
            continue
        if end.get('version') != DEMO_VERSION or type(end.get('count')) is not int or end['count'] < 1:
            raise ValueError('invalid retained episode manifest')
        if sorted(seen.get(ep, {})) != list(range(end['count'])):
            raise ValueError(f'missing or extra snapshots in retained episode {ep}')
        config = HILConfig(**end['contract']['config'])
        if end['contract'] != config.replay_contract() or bool(end.get('synthetic')) != (config.transport == 'fake'):
            raise ValueError('unsupported or inconsistent demo contract')
        directory = output / 'episodes' / ep
        # Reuse all live writer shape, range, causality and command-label checks,
        # without duplicating large arrays or writing another dataset.
        from omi_hil_rl.training.transition_replay import _spaces, _array
        spaces, action_space = _spaces(end['contract'])
        previous = None
        for step in range(end['count']):
            obs, nxt, action, meta = read_demo_step(directory, step, end)
            if set(obs) != set(spaces.spaces) or set(nxt) != set(spaces.spaces):
                raise ValueError('observation keys mismatch')
            for group in (obs, nxt):
                for key, space in spaces.spaces.items():
                    _array(group[key], space, key)
                if not np.all(group['history_mask']) or np.any(group['state'][:, :7]):
                    raise ValueError('incomplete history or joints enabled')
            _array(action, action_space, 'action')
            now, after = meta['observation_time_ns'], meta['next_observation_time_ns']
            if not 0 < now < after or (previous is not None and now != previous):
                raise ValueError('non-contiguous episode chronology')
            previous = after
        manifest = {k:v for k,v in end.items() if k not in ('kind','monotonic_ns','wall_time_ns','ros_time_ns')}
        manifest.update(raw_bag=str(source), conversion=SAMPLE_VERSION)
        pending_manifests.append((directory, manifest))
    if not pending_manifests:
        raise ValueError('no complete retained episodes; no dataset was published')
    for directory, manifest in pending_manifests:
        atomic_json(directory / 'demo.json', manifest)
    report = dict(version=SAMPLE_VERSION, source=str(source), episodes=len(pending_manifests),
                  samples=sum(m['count'] for _,m in pending_manifests),
                  excluded_episodes=sorted(set(seen) - {m['episode'] for _,m in pending_manifests}),
                  sessions=sessions, alignment='exact recorded observation windows; no nearest-frame reconstruction',
                  reward_available=False)
    atomic_json(output / 'conversion.json', report)
    (output / 'conversion_pending.json').unlink()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', type=Path, required=True, help='new collector session directory or its raw rosbag directory')
    parser.add_argument('--output', type=Path, required=True, help='new dataset directory')
    args = parser.parse_args()
    bag = args.bag / 'raw' if (args.bag / 'raw' / 'metadata.yaml').exists() else args.bag
    print(json.dumps(convert_records(bag_records(bag), args.output, source=bag.resolve()), indent=2))


if __name__ == '__main__':
    main()
