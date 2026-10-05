"""Pure source routing, including explicit stop on switching channels."""
import pytest
from omi_hil_rl.real.gamepad_control import command_routes


@pytest.mark.parametrize('mode', ['human', 'human_home', 'home_waiting', 'home_failed', 'home_unavailable'])
def test_manual_and_home_route_outside_policy_guard(mode):
    data = [1., 2., 3., 4., 5., 6.]
    assert command_routes(mode, data) == ('manual', [('manual', data)])


@pytest.mark.parametrize('mode', ['policy', 'paused_disconnected', 'paused_no_policy'])
def test_policy_and_pause_stay_on_guarded_channel(mode):
    assert command_routes(mode, [0.] * 6)[0] == 'policy'


def test_handoff_cancels_previous_channel_without_relabeling_policy_as_manual():
    data = [1.] * 6
    assert command_routes('human', data, 'policy') == (
        'manual', [('policy', [0.] * 6), ('manual', data)])
    assert command_routes('policy', data, 'manual') == (
        'policy', [('manual', [0.] * 6), ('policy', data)])
    assert command_routes('human_home', data, 'manual') == ('manual', [('manual', data)])
