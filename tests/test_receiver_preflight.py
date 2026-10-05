from types import SimpleNamespace as NS
import pytest
from omi_hil_rl.real.receiver_preflight import motion_connection_ready, resolve_routes
from omi_hil_rl.real.policy_gamepad import commands


def test_auto_routes_legacy_manual_only():
    assert resolve_routes('/omi/action/decision','/omi/controller_test/decision') == '/omi/controller_test/decision'
    with pytest.raises(ValueError,match='mismatch'):
        resolve_routes('/omi/action/decision','/omi/controller_test/decision','/omi/action/manual_decision')
    with pytest.raises(ValueError):resolve_routes('/omi/action/decision','/omi/action/decision')
    with pytest.raises(ValueError):resolve_routes('/other','/manual')


def test_motion_preflight_requires_both_receiver_authorizations():
    assert motion_connection_ready([NS(type=1, bool_value=True), NS(type=1, bool_value=True)])
    assert not motion_connection_ready([NS(type=1, bool_value=True), NS(type=1, bool_value=False)])
    assert not motion_connection_ready([NS(type=0, bool_value=True), NS(type=1, bool_value=True)])
    assert not motion_connection_ready([])


def test_resolved_topic_and_rgb_pass_to_children(tmp_path):
    args=NS(checkpoint=tmp_path/'a.pt',output=tmp_path,duration=3,device='cpu',gamepad='/missing',
        eef_reference='raw',policy_scale=1.,speed_mm_s=5,rotation_deg_s=5,execute=False,
        manual_topic='/omi/controller_test/decision',rgb_max_age_ms=500.)
    cmd,_=commands(args)
    assert cmd[0][cmd[0].index('--manual-topic')+1]==args.manual_topic
    assert cmd[1][cmd[1].index('--rgb-max-age-ms')+1]=='500.0'
    assert '--publish' not in cmd[0]
