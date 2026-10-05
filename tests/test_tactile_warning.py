from pathlib import Path
import argparse
import pytest
from omi_hil_rl.real.tactile_warning import WarningMonitor, positive


def test_normal_values_do_not_log_and_raw_force_preload_is_not_subtracted():
    logs = []
    m = WarningMonitor(logs.append, force_limit=4.)
    m.receive('A', [0., 0., -3., 0., 0., 0.], 0.)
    assert not logs
    m.receive('A', [0., 0., -4., 0., 0., 0.], .1)
    assert len(logs) == 1 and '|F|=4.00000 >= 4.00000' in logs[0]


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('values', [[-3., -4., 0., 0., 0., 0.], [0., 0., 0., 0., -.5, 0.]])
def test_either_finger_force_or_torque_logs(side, values):
    logs = []
    m = WarningMonitor(logs.append, force_limit=5., torque_limit=.5)
    m.receive(side, values, 0.)
    assert len(logs) == 1 and logs[0].startswith(side + ':')


def test_warning_rate_limit_is_independent_per_finger():
    logs = []
    m = WarningMonitor(logs.append, force_limit=2.)
    for t in (0., .1, .9):
        for side in ('A', 'B'):
            m.receive(side, [3., 0., 0., 0., 0., 0.], t)
    assert len(logs) == 2
    m.receive('A', [3., 0., 0., 0., 0., 0.], 1.)
    assert len(logs) == 3


def test_below_threshold_stops_warning_without_manual_reset():
    logs = []
    m = WarningMonitor(logs.append, force_limit=2.)
    m.receive('A', [3., 0., 0., 0., 0., 0.], 0.)
    m.receive('A', [1., 0., 0., 0., 0., 0.], 2.)
    assert len(logs) == 1


def test_invalid_values_log_without_crashing():
    logs = []
    m = WarningMonitor(logs.append, force_limit=2.)
    m.receive('A', [float('nan')] * 6, 0.)
    assert 'invalid wrench' in logs[0]


@pytest.mark.parametrize('value', ['nan', 'inf', '0', '-1'])
def test_invalid_parameters_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive(value)


def test_at_least_one_threshold_required():
    with pytest.raises(ValueError):
        WarningMonitor(lambda message: None)


def test_monitor_does_not_create_action_publishers_or_load_robot_sdk():
    source = (Path(__file__).resolve().parents[1] / 'src/omi_hil_rl/real/tactile_warning.py').read_text()
    assert 'create_publisher' not in source
    assert 'fx_robot' not in source
    assert 'filter_action(' not in source
    assert 'create_service' not in source
