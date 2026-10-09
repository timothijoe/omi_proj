import json
import shutil

import numpy as np
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.environment import FakeTransport
from omi_hil_rl.hil.exchange import read_episode, import_ready
from omi_hil_rl.hil.observation_storage import FrameWriter, ObservationReader, VERSION, save_archive
from omi_hil_rl.hil.periodic_bc_label import validate_bc_label
from omi_hil_rl.hil.periodic_control import PeriodicAudit
from omi_hil_rl.hil.periodic_review import PeriodicReview
from omi_hil_rl.hil.prepare_periodic_bc import prepare
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.training.transition_replay import TransitionReplay


def equal(actual, expected):
    assert actual.keys() == expected.keys()
    for key in expected:
        assert actual[key].dtype == expected[key].dtype
        assert actual[key].shape == expected[key].shape
        assert actual[key].tobytes() == expected[key].tobytes(), key


def small_frames(count):
    rng = np.random.default_rng(32)
    return [dict(rgb=rng.integers(0, 256, (3, 32, 32), dtype=np.uint8),
                 tactile=rng.normal(size=(10, 4, 4)).astype(np.float32),
                 state=rng.normal(size=14).astype(np.float32),
                 camera_mask=np.ones(2, np.float32), history_mask=np.asarray(1, np.uint8))
            for _ in range(count)]


def window(frames):
    assert len(frames) == 10
    return {k: np.stack([f[k] for f in frames]) for k in frames[0]}


def test_first_history_then_one_frame_with_random_access_and_no_tick_duplicates(tmp_path):
    writer = FrameWriter(tmp_path/'frames')
    frames = small_frames(49)
    old_size = 0
    for i in range(40):
        obs = window(frames[i:i+10])
        writer.write(tmp_path/f'{i}.npz', {'tick': i}, obs)
        assert len(writer.written) == 10+i
        from io import BytesIO
        old = BytesIO()
        np.savez_compressed(old, **{'observation__'+k: v for k, v in obs.items()})
        old_size += old.tell()
    # Delayed inference and terminal snapshots reuse exactly the same frames.
    writer.write(tmp_path/'late-action.npz', {}, window(frames[3:13]))
    writer.write(tmp_path/'boundary.npz', {}, window(frames[39:49]))
    assert len(writer.written) == 49
    reader = ObservationReader(cache_size=12)
    for i in [39, 0, 30, 8, 1, 39]:
        meta, obs = reader.read(tmp_path/f'{i}.npz')
        assert meta['tick'] == i
        equal(obs, window(frames[i:i+10]))
        obs['rgb'][:] = 0
        equal(reader.read(tmp_path/f'{i}.npz')[1], window(frames[i:i+10]))
        assert len(reader.cache) <= 12
    new_size = sum(p.stat().st_size for p in tmp_path.rglob('*.npz'))
    assert new_size < old_size / 4  # Small fixtures pay proportionally more ZIP overhead.


def test_gaps_partial_history_and_discontinuous_windows_are_exact(tmp_path):
    writer = FrameWriter(tmp_path/'frames')
    frames = small_frames(32)
    zero = {k: np.zeros_like(v) for k, v in frames[0].items()}
    windows = [window([zero]*9 + frames[:1]), window([zero]*8 + frames[:2]),
               window(frames[:3] + [zero]*2 + frames[5:10]),
               window(frames[20:30]), window(frames[1:11]), window(frames[22:32])]
    for i, obs in enumerate(windows):
        writer.write(tmp_path/f'{i}.npz', {}, obs)
    for i in reversed(range(len(windows))):
        equal(ObservationReader().read(tmp_path/f'{i}.npz')[1], windows[i])
    # Missing snapshots retain their status; they are not invented zero inputs.
    writer.write(tmp_path/'missing.npz', {'observation_present': False}, None)
    assert ObservationReader().read(tmp_path/'missing.npz') == ({'observation_present': False}, {})


@pytest.mark.parametrize('failure', ['missing', 'corrupt', 'version', 'length'])
def test_broken_frame_dependencies_fail_explicitly(tmp_path, failure):
    writer = FrameWriter(tmp_path/'frames')
    path = tmp_path/'0.npz'
    writer.write(path, {}, window(small_frames(10)))
    meta, _ = ObservationReader().read(path)
    ref = meta['observation_storage']['observation']
    frame = tmp_path/ref['directory']/(ref['frames'][0]+'.npz')
    if failure == 'missing':
        frame.rename(frame.with_suffix('.missing'))
    elif failure == 'corrupt':
        with np.load(frame) as data:
            values = {k: data[k].copy() for k in data.files if k != 'metadata'}
        values['rgb'][0, 0, 0] ^= 1
        save_archive(frame, {}, values)
    else:
        if failure == 'version':
            ref['version'] = 'unknown'
        else:
            ref['frames'].pop()
        save_archive(path, meta, {})
    with pytest.raises((FileNotFoundError, ValueError)):
        ObservationReader().read(path)


def test_legacy_full_windows_still_load(tmp_path):
    obs = window(small_frames(10))
    save_archive(tmp_path/'legacy.npz', {'old': True}, {'observation__'+k: v for k, v in obs.items()})
    metadata, actual = ObservationReader().read(tmp_path/'legacy.npz')
    assert metadata == {'old': True}
    equal(actual, obs)


def record_episode(run, name, config, *, gap=False):
    """True-shaped windows, sparse action cadence, and accepted human commands."""
    contract = config.replay_contract()
    template = FakeTransport(config)._observation()
    frames = []
    for i in range(16):
        frame = {k: v[0].copy() for k, v in template.items()}
        frame['rgb'].fill(i)
        frame['wrist_rgb'].fill(i+20)
        frame['tactile'].fill(i/100)
        frame['state'][7] = i/100
        frame['camera_mask'][:] = 1
        frames.append(frame)
    windows = [window(frames[i:i+10]) for i in range(7)]
    audit = PeriodicAudit(run, name, contract, 12, training=True, timing_policy='diagnostic_only_v1')
    action = np.full(6, .1, np.float32)
    physical = config.physical_action(action)
    wire = output_action(physical, config.sdk_convention)
    for i, obs in enumerate(windows):
        stamp = 1_000_000_000+i*100_000_000
        audit.submit('observation', (stamp, obs, {'source_receive_ns': {'eef': stamp}}))
        if i not in (0, 2, 5):
            continue
        send = stamp+160_000_000  # Completion can follow newer observation ticks.
        trace = dict(command_id=str(i), command_send_ns=send, observation_reference_ns=stamp,
                     action_source='human', label_candidate=True, execution_confirmed=False,
                     action_contract=contract['action_contract'], output_convention=config.sdk_convention,
                     normalized_action=action.tolist(), action_m_rad=physical.tolist(), wire_action=wire)
        audit.submit('tick', (dict(command_id=str(i), action_source='human', gate='human', command_trace=trace,
            observation_present=True, observation_reference_ns=stamp, command_send_ns=send,
            normalized_action=action.tolist(), wire_action=wire), obs))
        if not (gap and i == 2):
            audit.submit('receipt', dict(command_id=str(i), accepted=True, finished=False, status='queue_accepted',
                timestamp_ns=send+1_000_000, wire_action=wire, arm='A', delta_frame='base',
                action_source='human', control_mode='velocity_hold', nominal_duration_s=.1))
    result = audit.finish((dict(observation_present=True, observation_reference_ns=1_600_000_000,
        eef_receive_ns=1_600_000_000, command_send_ns=1_700_000_000), windows[-1]),
        dict(episode=name, policy_version=12, success=True, reason='success'))
    return result, windows


def test_periodic_export_import_bc_review_and_run_relocation(tmp_path):
    run = tmp_path/'source'
    run.mkdir()
    config = HILConfig(wrist_camera='required')
    (run/'session.json').write_text(json.dumps(dict(mode='human_rl_periodic_v1', contract=config.replay_contract())))
    result, windows = record_episode(run, 'first', config)
    split, _ = record_episode(run, 'second', config, gap=True)
    assert result['stored_observation_frames'] == 16
    assert result['observation_storage_version'] == VERSION
    assert result['transitions'] == 3 and len(result['segments']) == 1
    assert split['transitions'] == 2 and len(split['segments']) == 2
    source = run/'periodic_episodes/first'
    assert len(list(source.glob('frames/*.npz'))) == 16
    for p in list(source.glob('*.npz')) + list(run.glob('episodes/*/*.npz')):
        with np.load(p) as archive:
            assert not any(k.startswith(('observation__', 'next_observation__')) for k in archive.files)
    # Ready segments contain references, never another full image/history copy.
    ready = run/'episodes'/result['segments'][0]/'ready.json'
    manifest = json.loads(ready.read_text())
    records = list(read_episode(ready.parent, manifest))
    for record, before, after in zip(records, [0, 2, 5], [2, 5, 6]):
        equal(record['observation'], windows[before])
        equal(record['next_observation'], windows[after])
        validate_bc_label(config.replay_contract(), record['executed_action'], record)
    view = PeriodicReview(run)
    index = next(i for i, e in enumerate(view.episodes) if e['directory'].name == 'first')
    assert view.tick(index, 1, 9)['image'].startswith('data:image/png;base64,')
    assert prepare(run, tmp_path/'bc_index')['samples'] == 5
    from omi_hil_rl.hil.behavior_cloning import load_data
    data = load_data(json.loads((tmp_path/'bc_index/dataset.json').read_text()), config.replay_contract())
    assert sum(len(split[1]) for split in data.values()) == 5
    moved = tmp_path/'moved'
    shutil.move(run, moved)
    moved_ready = moved/'episodes'/result['segments'][0]/'ready.json'
    equal(next(read_episode(moved_ready.parent, manifest))['observation'], windows[0])
    replay = TransitionReplay(tmp_path/'replay', config.replay_contract(), 8, prefetch=False)
    try:
        assert import_ready(moved, replay) == 5
        assert replay.buffer.size() == 5
        assert import_ready(moved, replay) == 0
        for i in range(3):
            equal({k: v[i, 0] for k, v in replay.buffer.observations.items()}, records[i]['observation'])
    finally:
        replay.close()
