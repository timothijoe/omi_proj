"""Direct gamepad defaults and preview behavior; no robot or gripper connections."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('direct_gamepad_entry', ROOT / 'scripts/gamepad_test.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def test_existing_start_command_enables_project_gripper_without_extra_flags():
    parser = entry.build_parser()
    args = parser.parse_args(['--execute', '--device', '/dev/input/js0',
        '--topic', '/omi/controller_test/decision', '--rate', '10',
        '--home-button-code', '307', '--scale', '.5',
        '--output-convention', 'sdk-x-forward-z-left'])
    assert args.gripper_server == '192.168.14.11:55551'
    assert args.gripper_calibration == ROOT / 'tutorials/gripper_limits.json'
    assert args.gripper_sdk_root == ROOT / 'local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py'
    assert entry.calibration_from_args(args, parser) == dict(
        clamp_pos=63500, open_pos=-26500, max_itinerary=90000, speed_coe=3600)
    assert not args.no_gripper


def test_execute_uses_receiver_manual_topic_by_default():
    assert entry.build_parser().parse_args(['--execute']).topic == 'auto'


def test_explicit_gripper_configuration_still_overrides_defaults(tmp_path):
    args = entry.build_parser().parse_args(['--gripper-server', 'custom:1234',
        '--gripper-sdk-root', str(tmp_path), '--gripper-calibration', str(tmp_path / 'limits.json')])
    assert args.gripper_server == 'custom:1234'
    assert args.gripper_sdk_root == tmp_path
    assert args.gripper_calibration == tmp_path / 'limits.json'


@pytest.mark.parametrize('disabled', [False, True])
def test_direct_entry_ab_preview_and_explicit_disable(monkeypatch, capsys, disabled):
    from omi_hil_rl.real.gamepad_gripper import BTN_A, BTN_B
    states = iter([{}, {BTN_A: True}, {}, {BTN_B: True}])
    class Pad:
        axes = {}
        error = ''
        def __init__(self, *args):
            self.buttons = {}
        def poll(self):
            try:
                self.buttons = next(states)
            except StopIteration:
                raise KeyboardInterrupt
            return True
        def close(self):
            pass
    monkeypatch.setattr(entry, 'LinuxGamepad', Pad)
    monkeypatch.setattr(entry.time, 'sleep', lambda _: None)
    monkeypatch.setattr(sys, 'argv', ['gamepad_test.py'] + (['--no-gripper'] if disabled else []))
    entry.main()  # preview must never construct a vendor SDK
    output = capsys.readouterr().out
    if disabled:
        assert '夹爪已禁用' in output
        assert '夹爪 {' not in output
    else:
        assert '夹爪配置：192.168.14.11:55551' in output
        assert '"action": "close"' in output
        assert '"action": "open"' in output
        assert output.count('"status": "preview"') == 2
