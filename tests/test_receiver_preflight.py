from types import SimpleNamespace as NS
import pytest
from omi_hil_rl.real.receiver_preflight import motion_connection_ready, resolve_routes, subscription_identity
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


def endpoint(name='delta_ctrl_node', namespace='/', type_='std_msgs/msg/Float64MultiArray'):
    return NS(node_name=name, node_namespace=namespace, topic_type=type_)


def test_named_receiver_remains_default_requirement():
    assert subscription_identity([endpoint()]) == 'node_name'
    unknown = endpoint('_NODE_NAME_UNKNOWN_', '_NODE_NAMESPACE_UNKNOWN_')
    assert subscription_identity([unknown]) is None
    assert subscription_identity([unknown], allow_anonymous=True) == 'unique_topic_type'


@pytest.mark.parametrize('endpoints', [
    [], [endpoint('other_controller')], [endpoint(namespace='/other')],
    [endpoint('_NODE_NAME_UNKNOWN_', '_NODE_NAMESPACE_UNKNOWN_', 'std_msgs/msg/String')],
    [endpoint('_NODE_NAME_UNKNOWN_', '/')],
    [endpoint('_NODE_NAME_UNKNOWN_', '_NODE_NAMESPACE_UNKNOWN_')]*2,
    [endpoint('_NODE_NAME_UNKNOWN_', '_NODE_NAMESPACE_UNKNOWN_'), endpoint('other_controller')],
])
def test_anonymous_fallback_rejects_wrong_or_ambiguous_receiver(endpoints):
    assert subscription_identity(endpoints, allow_anonymous=True) is None


def test_resolved_topic_and_rgb_pass_to_children(tmp_path):
    args=NS(checkpoint=tmp_path/'a.pt',output=tmp_path,duration=3,device='cpu',gamepad='/missing',
        eef_reference='raw',policy_scale=1.,speed_mm_s=5,rotation_deg_s=5,execute=False,
        manual_topic='/omi/controller_test/decision',rgb_max_age_ms=500.)
    cmd,_=commands(args)
    assert cmd[0][cmd[0].index('--manual-topic')+1]==args.manual_topic
    assert cmd[1][cmd[1].index('--rgb-max-age-ms')+1]=='500.0'
    assert '--publish' not in cmd[0]
