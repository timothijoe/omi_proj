from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.real.robot_state_panel import Timeline, decode_record, panel


def test_decode_feedback_and_command_timestamp_fallback():
    header = NS(stamp=NS(sec=2, nanosec=3))
    msg = NS(header=header, arm_positions=list(range(14)), arm_velocities=[0]*14, arm_efforts=[0]*14)
    record = decode_record("feedback", msg, 5)
    assert record["stamp"] == 2_000_000_003 and record["clock"] == "header"
    assert len(record["values"]["positions"]) == 14
    command = decode_record("gripper_command", NS(data=.2), 9)
    assert command["stamp"] == 9 and command["clock"] == "bag_receive"
    msg.arm_positions[0] = float("nan")
    with pytest.raises(ValueError):
        decode_record("feedback", msg, 5)
    with pytest.raises(ValueError):
        decode_record("target", NS(header=header, positions=[1, 2]), 5)


def test_past_only_selection_stale_and_loop():
    records = {"target": [dict(stamp=s, clock="header", values={"positions": [1]*7}) for s in (10**9, 2*10**9)]}
    timeline = Timeline(records)
    assert timeline.at("target", 999)[1] == "WAITING"
    assert timeline.at("target", 2*10**9)[0]["stamp"] == 2*10**9
    assert timeline.at("target", 10**9)[0]["stamp"] == 10**9  # loop resets lookup
    assert timeline.at("target", 1_500_000_000)[1] == "STALE"
    assert timeline.at("feedback", 10**9)[1] == "WAITING"
    fresh = panel(timeline, 2*10**9, 1840)
    stale = panel(timeline, 2*10**9, 1840, wall_age=1)
    assert fresh.shape == (340, 1840, 3) and fresh.dtype == np.uint8
    assert np.any(fresh != stale)


def test_robot_module_has_no_command_publisher():
    from pathlib import Path
    import omi_hil_rl.real.robot_state_panel as module
    source = Path(module.__file__).read_text()
    assert 'create_publisher(Image, "/omi/observation_robot/dashboard"' in source
    assert source.count("create_publisher(") == 1


def test_local_config_defaults_and_environment_override(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    helper = Path(__file__).resolve().parents[1] / "scripts/robot_viewer_env.sh"
    config = tmp_path / "local/robot_state/viewer.env"
    config.parent.mkdir(parents=True)
    config.write_text('omi_viewer_marvin_setup="/a path/install/setup.bash"\n')
    env = {k: v for k, v in os.environ.items() if k not in (
        "OMI_MARVIN_MSGS_SETUP", "OMI_DAIMON_SDK_ROOT", "OMI_ROBOT_VIEWER_CONFIG")}
    command = ['bash', '-c', 'source "$1" "$2" || exit; printf "%s\\n" "$OMI_MARVIN_MSGS_SETUP" "$OMI_DAIMON_SDK_ROOT"',
               'test', str(helper), str(tmp_path)]
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ['/a path/install/setup.bash', str(tmp_path / 'local/vendor/daimon_tactile')]
    env['OMI_DAIMON_SDK_ROOT'] = '/override/sdk'
    assert subprocess.run(command, env=env, capture_output=True, text=True, check=True).stdout.splitlines()[1] == '/override/sdk'
    env['OMI_ROBOT_VIEWER_CONFIG'] = str(tmp_path / 'missing.env')
    assert subprocess.run(command, env=env, capture_output=True).returncode != 0
