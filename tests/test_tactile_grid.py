import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ros2/omi_sensors'))
from omi_sensors.tactile_grid import block_mean, prepare_fields, topic_root


def test_mean_matches_training_pool_and_preserves_axes():
    yy, xx = np.mgrid[:288, :384]
    field = np.stack((xx, -yy), axis=-1).astype(np.float32)
    result = block_mean(field)
    assert result.shape == (16, 24, 2)
    assert result.dtype == np.float32 and result.flags.c_contiguous
    np.testing.assert_array_equal(result[..., 0], np.broadcast_to(7.5 + 16 * np.arange(24), (16, 24)))
    np.testing.assert_array_equal(result[..., 1], np.broadcast_to(-(8.5 + 18 * np.arange(16))[:, None], (16, 24)))
    from omi_hil_rl.training.bag_bc_data import pool_field
    np.testing.assert_array_equal(result.transpose(2, 0, 1), pool_field(field))
    assert field.nbytes == result.nbytes * 288


def test_mode_preserves_full_and_filters_grid():
    field = np.full((288, 384, 2), -3.25, dtype=np.float32)
    arrays = dict(raw=np.zeros((480, 640), np.uint8), infer=np.zeros((270, 360), np.uint8),
                  deformation=field, shear=field.copy(), depth=field[..., 0], wrench=np.arange(6.))
    full, metadata = prepare_fields(arrays, 'full')
    assert full is arrays and metadata == {}
    grid, metadata = prepare_fields(arrays, 'grid24x16')
    assert set(grid) == {'deformation', 'shear', 'depth', 'wrench'}
    assert grid['wrench'] is arrays['wrench']
    assert grid['depth'].shape == (16, 24)
    assert np.all(grid['deformation'] == -3.25)
    assert not np.shares_memory(grid['deformation'], field)
    assert metadata['resampling']['vector_scale'] == 1.0
    assert metadata['schema_version'] == 3
    assert topic_root('full') == '/omi/tactile'
    assert topic_root('grid24x16') == '/omi/tactile_grid24x16'


@pytest.mark.parametrize('value', [np.zeros((384, 288, 2), np.float32),
    np.zeros((288, 384, 2), np.uint8), np.full((288, 384, 2), np.nan),
    np.zeros((288, 384, 3), np.float32)])
def test_invalid_field_fails_closed(value):
    with pytest.raises(ValueError):
        block_mean(value)


def test_invalid_mode():
    with pytest.raises(ValueError):
        prepare_fields({}, 'typo')


def test_launcher_plan_and_dashboard_guard():
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'ros2/omi_sensors'), OMI_PROJECT_ROOT=str(ROOT))
    base = [sys.executable, '-m', 'omi_sensors.live_launcher', '--plan', '--pc-host', '127.0.0.1']
    result = subprocess.run(base + ['tactile', '--tactile-mode', 'grid24x16'], env=env,
                            capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    assert plan['commands'][0][-3:] == ['live', '--tactile-mode', 'grid24x16']
    result = subprocess.run(base + ['tactile', '--tactile-mode', 'full'], env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['commands'][0][-1] == 'live'
    result = subprocess.run(base + ['all', '--tactile-mode', 'grid24x16'], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 2 and 'requires component tactile' in result.stderr


@pytest.mark.parametrize('mode,publish_raw', [('full',False), ('grid24x16',False), ('grid24x16',True)])
def test_ros_fake_transport(mode, publish_raw, tmp_path, monkeypatch):
    rclpy = pytest.importorskip('rclpy')
    from sensor_msgs.msg import Image
    from std_msgs.msg import String
    config = json.loads((ROOT / 'ros2/omi_sensors/config/sdk_dashboard.example.json').read_text())
    config['domain_id'] = 187
    config['realsense']['enabled'] = False
    path = tmp_path / 'sensors.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('ROS_DOMAIN_ID', '187')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    monkeypatch.setenv('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
    monkeypatch.setenv('PYTHONPATH', str(ROOT / 'ros2/omi_sensors') + os.pathsep + os.environ.get('PYTHONPATH', ''))
    root = topic_root(mode)
    rclpy.init(args=[])
    node = rclpy.create_node('grid_transport_test')
    received = {}
    subscriptions = []
    for side in ('a', 'b'):
        for kind in ('deformation', 'shear', 'metadata'):
            key = side, kind
            subscriptions.append(node.create_subscription(String if kind == 'metadata' else Image,
                root + '/' + side + '/' + kind,
                lambda msg, key=key: received.__setitem__(key, msg), 10))
    if publish_raw:
        for side in ('a','b'):
            subscriptions.append(node.create_subscription(Image, '/omi/tactile/'+side+'/raw',
                lambda msg, side=side: received.__setitem__((side,'raw'),msg),10))
    expected_count = 8 if publish_raw else 6
    child = subprocess.Popen([sys.executable, '-m', 'omi_sensors.cli', '--config', str(path),
        'fake', '--duration', '4', '--tactile-mode', mode] + (['--publish-raw'] if publish_raw else []),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 7
        while len(received) < expected_count and time.monotonic() < deadline:
            if child.poll() is not None:
                stdout, stderr = child.communicate()
                pytest.fail('publisher exited before reception: ' + str((stdout, stderr)))
            rclpy.spin_once(node, timeout_sec=0.1)
        assert len(received) == expected_count
        names = {name for name, _ in node.get_topic_names_and_types()}
        if mode == 'grid24x16':
            if not publish_raw:
                assert not any(name.startswith('/omi/tactile/') for name in names)
            assert root + '/a/raw' not in names
        else:
            assert root + '/a/raw' in names
        for side in ('a', 'b'):
            msg = received[side, 'deformation']
            assert msg.encoding == '32FC2'
            assert (msg.height, msg.width) == ((16, 24) if mode == 'grid24x16' else (48, 64))
            assert len(msg.data) == msg.height * msg.width * 8
            assert msg.step == msg.width * 8 and msg.header.frame_id == 'tactile_' + side
            metadata = json.loads(received[side, 'metadata'].data)
            assert metadata['schema_version'] == (3 if mode == 'grid24x16' else 2)
            assert metadata['timestamp_kind'] == 'synthetic_host_time'
            if publish_raw:
                assert received[side,'raw'].encoding == 'mono8'
                assert 'raw' not in metadata['omitted_fields']
                assert metadata['raw_topic'] == '/omi/tactile/'+side+'/raw'
        stdout, stderr = child.communicate(timeout=7)
        assert child.returncode == 0, (stdout, stderr)
    finally:
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=5)
        node.destroy_node()
        rclpy.shutdown()
