import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from omi_hil_rl.real.tag_handeye import (PoseHistory, StableCapture, append_sample,
                                       coverage, solve, atomic_json, pose_message)
from omi_hil_rl.real.tag_follow import load_calibration


def pose(p=(0., 0., 0.), r=(0., 0., 0.)):
    t = np.eye(4)
    t[:3, :3] = cv2.Rodrigues(np.array(r, dtype=float))[0]
    t[:3, 3] = p
    return t


def dataset(count=21, noise=False):
    rng = np.random.default_rng(42)
    x = pose((.2, -.4, 1.), (.3, -.2, .5))
    z = pose((.02, -.03, .08), (-.3, .1, -.2))
    samples = []
    for _ in range(count):
        a = pose(rng.uniform(-.2, .2, 3), rng.uniform(-.6, .6, 3))
        b = np.linalg.inv(x) @ a @ z
        if noise:
            b = b @ pose(rng.normal(0, .0002, 3), rng.normal(0, .0007, 3))
        samples.append(dict(A=a.tolist(), B=b.tolist()))
    return samples, x, z


def test_recovers_both_transforms_and_follow_file_contract(tmp_path):
    samples, x, z = dataset()
    result = solve(samples)
    np.testing.assert_allclose(result['X'], x, atol=1e-9)
    np.testing.assert_allclose(result['Z'], z, atol=1e-9)
    assert result['validation_trans_mm_rms'] < 1e-6
    path = tmp_path/'handeye_result.json'
    atomic_json(path, result)
    xx, zz = load_calibration(path)
    np.testing.assert_allclose(xx, x, atol=1e-9)
    np.testing.assert_allclose(zz, z, atol=1e-9)


def test_noisy_measurements_cross_validate():
    samples, x, z = dataset(noise=True)
    result = solve(samples)
    assert result['residual_trans_mm_mean'] < 1.
    assert result['validation_trans_mm_rms'] < 2.
    np.testing.assert_allclose(np.array(result['X'])[:3, 3], x[:3, 3], atol=.002)


@pytest.mark.parametrize('count', [0, 1, 14])
def test_insufficient_samples_cannot_produce_calibration(count):
    with pytest.raises(ValueError, match='at least 15'):
        solve(dataset(count)[0])


@pytest.mark.parametrize('kind', ['translation', 'single_axis', 'tiny_rotation'])
def test_degenerate_pose_coverage_rejected(kind):
    aa = []
    for i in range(15):
        r = (0, 0, i*.08) if kind == 'single_axis' else (
             (.0001*i, .0002*i*i, 0) if kind == 'tiny_rotation' else (0, 0, 0))
        aa.append(dict(A=pose((i*.02, 0, 0), r).tolist(), B=np.eye(4).tolist()))
    with pytest.raises(ValueError, match='rotation coverage'):
        solve(aa)


def test_corrupt_pair_fails_quality_instead_of_writing_false_result(tmp_path):
    samples, _, _ = dataset()
    samples[5]['B'][0][3] += .1
    path = tmp_path/'handeye_result.json'
    path.write_text('existing result')
    with pytest.raises(ValueError, match='quality rejected'):
        atomic_json(path, solve(samples))
    assert path.read_text() == 'existing result'


def test_pose_history_matches_image_capture_time_not_current_tcp():
    h = PoseHistory()
    for i in range(20):
        h.add(1+i*.05, pose((i*.01, 0, 0)))
    stamp, a = h.match(1.505)
    assert stamp == pytest.approx(1.5)
    assert a[0, 3] == pytest.approx(.1)
    with pytest.raises(ValueError, match='50ms'):
        h.match(.8)
    with pytest.raises(ValueError, match='backwards'):
        h.add(1., pose())
    assert not h.values


def test_stationary_capture_uses_post_request_frames_and_averages():
    c = StableCapture(10.)
    a, b = pose((.3, 0, 0)), pose((0, 0, .5))
    assert c.add(9.9, 9.9, a, b, a, 10.3) is None
    for i in range(10):
        stamp = 10. + i*.1
        result = c.add(stamp, stamp+.01, a, b, a, stamp+.4)
    assert result['frames'] == 10
    np.testing.assert_allclose(result['A'], a)
    np.testing.assert_allclose(result['B'], b)
    assert result['max_pair_skew_ms'] == pytest.approx(10)


@pytest.mark.parametrize('kind', ['current_motion', 'burst_motion', 'tag_jump', 'delay', 'skew'])
def test_capture_rejects_motion_delay_and_mispairing(kind):
    c = StableCapture(10.)
    a, b = pose(), pose((0, 0, .5))
    c.add(10., 10., a, b, a, 10.4)
    if kind == 'current_motion': current = pose((.01, 0, 0))
    else: current = a
    if kind == 'burst_motion': a = current = pose((.01, 0, 0))
    if kind == 'tag_jump': b = pose((.02, 0, .5))
    with pytest.raises(ValueError):
        c.add(10.1, 10.3 if kind == 'skew' else 10.1, a, b, current,
              12. if kind == 'delay' else 10.5)


def test_duplicate_samples_and_bad_frame_rejected():
    samples = []
    item = dict(A=pose().tolist(), B=pose().tolist())
    append_sample(samples, item)
    with pytest.raises(ValueError, match='Too similar'):
        append_sample(samples, item)
    msg = NS(header=NS(frame_id='sdk_base'))
    with pytest.raises(ValueError, match='base_link'):
        pose_message(msg)


def test_readonly_entry_import_and_offline_solve(tmp_path):
    path = Path(__file__).resolve().parents[1]/'ros2/marker_detect/tag_handeye_calibration.py'
    # The entry contains subscriptions only: no motion publisher or SDK calls.
    assert 'create_publisher' not in path.read_text()
    spec = importlib.util.spec_from_file_location('calibration_entry', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path/'samples.json'
    output = tmp_path/'handeye_result.json'
    atomic_json(source, dict(schema='omi-tag10-handeye-samples-v1', samples=dataset()[0],
                             context=dict(camera_frame='camera_color_optical_frame')))
    module.main(['--solve-samples', str(source), '--output', str(output)])
    load_calibration(output)
