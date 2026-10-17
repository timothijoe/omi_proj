"""Exercise launcher ownership and shutdown with fake devices, never real ROS."""
import json
import os
from pathlib import Path
import pty
import signal
import subprocess
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/start_common_live.sh'
WORKER = r'''#!/usr/bin/python3
import json, os, signal, sys, time
from pathlib import Path

def event(kind, **extra):
    with open(os.environ['MOCK_EVENTS'], 'a') as stream:
        stream.write(json.dumps(dict(kind=kind, pid=os.getpid(), **extra)) + '\n')

args = sys.argv[1:]
mode = os.environ.get('MOCK_MODE', '')
name = Path(sys.argv[0]).name
if name == 'ping':
    sys.exit(0)
if name == 'ros2':
    if args[:2] == ['pkg', 'prefix']:
        sys.exit(0)
    if args[:2] == ['topic', 'echo']:
        event('topic', topic=args[2], message_type=args[3])
        if mode == 'topic-fail':
            time.sleep(10)
        sys.exit(0)
    name = 'robot' if args[1] == 'arm_delta_cmd' else 'd435'
elif args[0] in ('camera', 'tactile'):
    name = args[0]
elif args[0] == 'prepare':
    event('prepare', args=args)
    target = Path(args[args.index('--run') + 1])
    target.mkdir(parents=True)
    sys.exit(0)
else:
    name = 'action'

def stop(sig, frame):
    if name == 'action':
        time.sleep(.25)  # Model an actor draining a writer/checkpoint.
        event('saved')
    event('stopped', name=name)
    sys.exit(0)

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
event('started', name=name, args=args)
if name == 'action':
    if args[0].endswith('gamepad_test.py'):
        input('mock gamepad Enter: ')
        event('stdin-ok')
    if mode not in ('interrupt', 'service-fail'):
        time.sleep(.3)
        event('saved')
        sys.exit(0)
while True:
    if mode == 'service-fail' and name == 'd435':
        if '"name": "action"' in Path(os.environ['MOCK_EVENTS']).read_text():
            event('failed', name=name)
            sys.exit(7)
    if mode == 'startup-fail' and name == 'd435':
        sys.exit(7)
    time.sleep(.05)
'''


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def rig(tmp_path):
    script = tmp_path / 'scripts/start_common_live.sh'
    # Only relocate the system ROS setup; all process management is unchanged.
    executable(script, SCRIPT.read_text().replace(
        'ros_setup="/opt/ros/$ROS_DISTRO/setup.bash"',
        'ros_setup="$root/mock_setup.bash"'))
    (tmp_path / 'mock_setup.bash').write_text('export PATH="$root/bin:$PATH"\n')
    executable(tmp_path / 'local/ros2/robot_controller_ws/install/local_setup.bash', '')
    for name in ('ros2', 'ping', 'worker'):
        executable(tmp_path / 'bin' / name, WORKER)
    for name in ('.venv/bin/python', 'local/cuda-env/bin/python',
                 'local/venvs/daimon312/bin/python'):
        executable(tmp_path / name, WORKER)
    for name, role in (
        ('start_daimon_live.sh', ''), ('collect_rl_episodes.sh', 'collect'),
        ('run_bc_episodes.sh', 'bc'), ('run_async_rl.sh', 'rl'),
        ('prepare_bc_rl.sh', 'prepare'),
    ):
        executable(tmp_path / 'scripts' / name,
                   f'#!/bin/bash\nexec worker {role} "$@"\n')
    for directory in ('bc source', 'old run'):
        folder = tmp_path / directory
        folder.mkdir()
        for name in ('actor.pt', 'config.json', 'async_session.json'):
            (folder / name).touch()
    (tmp_path / 'pad').touch()
    return tmp_path


def events(root):
    path = root / 'events.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def run(rig, args, mode='', input_text='', interrupt=False):
    master, slave = pty.openpty()
    env = dict(os.environ, MOCK_EVENTS=str(rig / 'events.jsonl'), MOCK_MODE=mode)
    proc = subprocess.Popen(
        ['bash', str(rig / 'scripts/start_common_live.sh'), *args],
        stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True, start_new_session=True)
    os.close(slave)
    try:
        if input_text:
            os.write(master, input_text.encode())
        if interrupt:
            deadline = time.monotonic() + 15
            while not any(e['kind'] == 'started' and e['name'] == 'action' for e in events(rig)):
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.fail('actor did not start: ' + proc.communicate(timeout=2)[0])
                time.sleep(.05)
            proc.send_signal(signal.SIGINT)
        stdout = proc.communicate(timeout=25)[0]
        # Check BEFORE emergency cleanup, so a leaked child cannot be hidden by
        # this test harness's finally block.
        for event in events(rig):
            if event['kind'] == 'started':
                with pytest.raises(ProcessLookupError):
                    os.kill(event['pid'], 0)
        return proc.returncode, stdout
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        # Never leave mock children running if an assertion/timeout exposes a bug.
        for event in events(rig):
            if event['kind'] == 'started':
                try:
                    os.kill(event['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        os.close(master)


def assert_clean_shutdown(rig):
    records = events(rig)
    saved = next(i for i, e in enumerate(records) if e['kind'] == 'saved')
    stops = [(i, e['name']) for i, e in enumerate(records) if e['kind'] == 'stopped']
    services = [(i, name) for i, name in stops if name != 'action']
    assert all(i > saved for i, _ in services)
    assert services[-1][1] == 'robot'
    for event in records:
        if event['kind'] == 'started':
            with pytest.raises(ProcessLookupError):
                os.kill(event['pid'], 0)


def test_preview_does_not_load_ros_or_create_runtime(rig):
    (rig / 'mock_setup.bash').write_text('exit 99\n')
    code, output = run(rig, ['--dry-run'])
    assert code == 0
    assert all(mode in output for mode in ('gamepad', 'collect', 'bc', 'rl-new', 'rl-resume'))
    assert '--weights-only' in output
    assert '--no-gripper' not in output
    assert not (rig / 'local/common_live').exists()
    assert not events(rig)


@pytest.mark.parametrize('action', ['collect', 'bc', 'rl-new', 'rl-resume'])
def test_single_action_and_orderly_device_shutdown(rig, action):
    args = ['--action', action, '--gamepad', str(rig / 'pad'), '--bc-run', 'bc source']
    if action.startswith('rl-'):
        args += ['--run', 'new run' if action == 'rl-new' else 'old run']
    code, output = run(rig, args)
    assert code == 0, output
    records = events(rig)
    actors = [e for e in records if e['kind'] == 'started' and e['name'] == 'action']
    assert len(actors) == 1
    assert len([e for e in records if e['kind'] == 'topic']) == 11
    assert bool([e for e in records if e['kind'] == 'prepare']) == (action == 'rl-new')
    assert_clean_shutdown(rig)


def test_menu_and_gamepad_keep_terminal_input(rig):
    code, output = run(rig, ['--gamepad', str(rig / 'pad')], input_text='1\n\n')
    assert code == 0, output
    assert any(e['kind'] == 'stdin-ok' for e in events(rig))
    assert_clean_shutdown(rig)


def test_interrupt_waits_for_actor_save_before_devices(rig):
    code, output = run(rig, ['--action', 'collect', '--gamepad', str(rig / 'pad')],
                       mode='interrupt', interrupt=True)
    assert code == 130, output
    assert_clean_shutdown(rig)


def test_new_rl_refuses_existing_directory(rig):
    code, output = run(rig, ['--action', 'rl-new', '--gamepad', str(rig / 'pad'),
                            '--bc-run', 'bc source', '--run', 'old run'])
    assert code != 0
    assert '新 RL 目录已存在' in output
    assert not any(e['kind'] == 'prepare' for e in events(rig))
    assert not any(e['kind'] == 'started' and e['name'] == 'action' for e in events(rig))


def test_no_gripper_is_forwarded_to_rl(rig):
    code, output = run(rig, ['--action', 'rl-resume', '--gamepad', str(rig / 'pad'),
                            '--run', 'old run', '--no-gripper'])
    assert code == 0, output
    actor = next(e for e in events(rig) if e['kind'] == 'started' and e['name'] == 'action')
    assert '--no-gripper' in actor['args']
    assert_clean_shutdown(rig)


@pytest.mark.parametrize('mode', ['startup-fail', 'topic-fail', 'service-fail'])
def test_device_failure_aborts_and_cleans_up(rig, mode):
    code, output = run(rig, ['--action', 'collect', '--gamepad', str(rig / 'pad'),
                            '--ready-timeout', '1'], mode=mode)
    assert code != 0, output
    records = events(rig)
    if mode == 'service-fail':
        assert_clean_shutdown(rig)
    else:
        assert not any(e['kind'] == 'started' and e['name'] == 'action' for e in records)
        for event in records:
            if event['kind'] == 'started':
                with pytest.raises(ProcessLookupError):
                    os.kill(event['pid'], 0)
