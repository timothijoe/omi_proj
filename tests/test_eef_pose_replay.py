"""Offline checks for recorded pose-to-controller conversion (no ROS publishing)."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('replay_eef_pose', Path(__file__).parents[1]/'scripts/replay_eef_pose.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def test_base_rotation_noncommuting_and_sign():
    # Start +90deg X, then a base +90deg Y: q_new = q_y * q_x.
    v = np.sqrt(.5)
    a = np.array([.3, -.2, .7, v, 0, 0, v])
    b = np.array([.32, -.18, .71, .5, .5, -.5, .5])
    d = r.delta(a, b)
    np.testing.assert_allclose(d[3:], [0, np.pi/2, 0], atol=1e-14)
    result = r.integrate(a, d)
    np.testing.assert_allclose(result, b, atol=1e-14)
    b[3:] *= -1
    np.testing.assert_allclose(r.delta(a, b), d, atol=1e-14)


def test_slerp_and_endpoint():
    p = np.array([[0,0,0,0,0,0,1], [2,0,0,0,0,-1,0]], dtype=float)
    out = r.interpolate(np.array([0., 2.]), p, np.array([0.,1.,2.,3.]))
    np.testing.assert_allclose(out[:,0], [0,1,2,2])
    assert abs(np.linalg.norm(r.delta(p[0],out[1])[3:])-np.pi/2) < 1e-14
    np.testing.assert_allclose(out[-1], out[-2])


def test_invalid_quaternion():
    with pytest.raises(ValueError): r.quat([0,0,0,0])
    with pytest.raises(ValueError): r.quat([0,0,0,float('nan')])


def test_real_converted_bag_matches_project_contract():
    from omi_hil_rl.training.eef_action import between, apply
    path = Path(__file__).parents[1]/'local/eef_replay/oct04_right_bag002_probe_s005'
    if not path.exists(): pytest.skip('Local source dataset absent')
    m, d = r.load_dataset(path)
    for i in range(len(d['action_m_rad'])):
        np.testing.assert_allclose(d['action_m_rad'][i], between(d['pose'][i], d['pose'][i+1]), atol=1e-14)
        assert np.linalg.norm(between(apply(d['pose'][i], d['action_m_rad'][i]),d['pose'][i+1])) < 1e-12
    assert m['max_step_translation_mm'] < 1
    assert m['max_step_rotation_deg'] < .2


def test_comparison_ideal_and_wrong_dataset(tmp_path):
    path = Path(__file__).parents[1]/'local/eef_replay/oct04_right_bag002_probe_s005'
    if not path.exists(): pytest.skip('Local source dataset absent')
    m, d = r.load_dataset(path)
    rows = [dict(kind='start', monotonic_s=1., origin_s=1., trajectory_sha256=m['trajectory_sha256'])]
    rows += [dict(kind='feedback',monotonic_s=1+float(t),pose=p.tolist()) for t,p in zip(d['t'],d['pose'])]
    rows.append(dict(kind='complete'))
    log=tmp_path/'test.jsonl'; log.write_text('\n'.join(json.dumps(x) for x in rows))
    r.compare(path,log)
    report=json.loads(log.with_suffix('.comparison.json').read_text())
    assert report['position_max_mm'] < 1e-9
    assert report['rotation_max_deg'] < 1e-9
    rows[0]['trajectory_sha256']='wrong'
    log.write_text('\n'.join(json.dumps(x) for x in rows))
    with pytest.raises(ValueError,match='another trajectory'): r.compare(path,log)
