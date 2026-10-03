import sys
import os
import json
import subprocess
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ros2/omi_sensors'))
from omi_sensors.live_launcher import transport_environment
from omi_sensors.cli import environment


def test_tactile_numeric_defaults_and_overrides():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root/'ros2/omi_sensors'), OMI_PROJECT_ROOT=str(root))
    base = [sys.executable, '-m', 'omi_sensors.live_launcher', 'tactile',
            '--transport', 'network', '--pc-host', '127.0.0.1', '--plan']
    for extra, expected, wrench in (([], True, False), (['--no-tactile-depth'], False, False),
                            (['--no-tactile-wrench'], True, False),
                            (['--tactile-mode', 'full'], False, False),
                            (['--tactile-depth', '--tactile-wrench'], True, True),
                            (['--tactile-depth', '--tactile-wrench', '--tactile-mode', 'grid24x16'], True, True)):
        result = subprocess.run(base + extra, env=env, capture_output=True, text=True, check=True)
        plan = json.loads(result.stdout)
        assert plan['config']['tactile']['enable_depth'] is expected
        assert plan['config']['tactile']['enable_wrench'] is wrench
        assert plan['config']['realsense']['enable_depth'] is False
        assert plan['environment']['ROS_AUTOMATIC_DISCOVERY_RANGE'] == 'SUBNET'
        assert plan['tactile_mode'] == ('full' if 'full' in extra else 'grid24x16')
    plan = json.loads(subprocess.run(base+['--publish-raw','--tactile-wrench'], env=env,
                                    capture_output=True,text=True,check=True).stdout)
    assert plan['publish_raw'] and plan['commands'][0][-1] == '--publish-raw'
    assert plan['config']['tactile']['enable_wrench']
    for component in ('all', 'view', 'camera'):
        if component != 'camera' and importlib.util.find_spec('yaml') is None:
            continue  # Full GUI-plan coverage also runs under ROS system Python.
        command = base.copy()
        command[3] = component
        plan = json.loads(subprocess.run(command, env=env, capture_output=True, text=True, check=True).stdout)
        assert plan['tactile_mode'] == 'full'
        assert not plan['config']['tactile']['enable_depth']
        assert not plan['config']['tactile']['enable_wrench']


def test_network_survives_nested_tactile_launch(monkeypatch):
    monkeypatch.setenv('FASTRTPS_DEFAULT_PROFILES_FILE', '/old/localhost.xml')
    monkeypatch.setenv('FASTDDS_DEFAULT_PROFILES_FILE', '/old/localhost.xml')
    env = transport_environment({'domain_id': 13}, Path('/project'), 'network')
    assert 'FASTRTPS_DEFAULT_PROFILES_FILE' not in env
    assert 'FASTDDS_DEFAULT_PROFILES_FILE' not in env
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for _ in range(2):
        child = environment({'domain_id': 13})
        assert child['ROS_DOMAIN_ID'] == '13'
        assert child['ROS_LOCALHOST_ONLY'] == '0'
        assert child['ROS_AUTOMATIC_DISCOVERY_RANGE'] == 'SUBNET'


def test_local_mode_overrides_inherited_network(monkeypatch):
    monkeypatch.setenv('OMI_SENSOR_DISCOVERY_RANGE', 'SUBNET')
    env = transport_environment({'domain_id': 13}, Path('/project'), 'default')
    assert env['OMI_SENSOR_DISCOVERY_RANGE'] == 'LOCALHOST'
    assert env['ROS_LOCALHOST_ONLY'] == '1'


def test_default_transport_unchanged():
    env = transport_environment({'domain_id': 88}, Path('/project'), 'default')
    assert env['ROS_LOCALHOST_ONLY'] == '1'
    assert env['RMW_FASTRTPS_PUBLICATION_MODE'] == 'ASYNCHRONOUS'


def test_shm_profile_overrides_legacy_flag(monkeypatch):
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    env = transport_environment({'domain_id': 88}, Path('/project'), 'local-shm')
    assert 'ROS_LOCALHOST_ONLY' not in env
    assert env['RMW_FASTRTPS_PUBLICATION_MODE'] == 'SYNCHRONOUS'
    assert env['RMW_IMPLEMENTATION'] == 'rmw_fastrtps_cpp'
    assert env['FASTRTPS_DEFAULT_PROFILES_FILE'] == '/project/ros2/omi_sensors/config/large_image_shm.xml'
