import math
from types import SimpleNamespace as NS
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from omi_hil_rl.real.policy_action import policy_trace,candidate_reason,SDK_FROM_POLICY,SDK_CONVENTION
from omi_hil_rl.real.eef_reference import reference_pose
from omi_hil_rl.real.gamepad_control import Arbiter,Mapping,wire_action
from omi_hil_rl.real.policy_gamepad import commands
from omi_hil_rl.training.eef_action import between,apply


def test_gt_and_prediction_share_exact_sdk_boundary():
    current=np.r_[[.5,.03,.8],Rotation.from_euler('xyz',[.2,-.1,.3]).as_quat()]
    action=np.array([.0002,-.0003,.0001,.004,-.006,.002])
    target=apply(current,action)
    gt=between(current,target)
    np.testing.assert_allclose(gt,action,atol=1e-15)
    # A fixed base translation changes input position, not the relative label.
    shifted_gt=between(reference_pose(current,'bag-baseline-v1'),reference_pose(target,'bag-baseline-v1'))
    np.testing.assert_allclose(shifted_gt,gt,atol=1e-15)
    a=Arbiter(Mapping());a.select(True,False,{},1.)
    assert a.offer(action,1.01,1.02)
    source,selected=a.select(True,False,{},1.03)
    assert source=='policy' and a.selected_policy_stamp==1.01
    out=wire_action(selected,SDK_CONVENTION)
    np.testing.assert_allclose(out,policy_trace(gt)['sdk_preview_mm_abc_deg'],atol=1e-12)
    Q=SDK_FROM_POLICY
    R0=Rotation.from_quat(current[3:]).as_matrix();R1=Rotation.from_quat(target[3:]).as_matrix()
    np.testing.assert_allclose(Q@current[:3]+np.array(out[:3])/1000,Q@target[:3],atol=1e-15)
    np.testing.assert_allclose(Rotation.from_euler('xyz',out[3:],degrees=True).as_matrix()@Q@R0,Q@R1,atol=1e-12)


def test_tool_offset_is_not_constant_base_translation_for_rotating_arm():
    pose=np.array([0.,0.,0.,0.,0.,0.,1.]);action=np.array([0.,0.,0.,0.,0.,.2])
    future=apply(pose,action);r=np.array([.1,0.,0.])
    p0=pose.copy();p1=future.copy()
    p0[:3]+=Rotation.from_quat(pose[3:]).apply(r);p1[:3]+=Rotation.from_quat(future[3:]).apply(r)
    assert np.linalg.norm(between(p0,p1)[:3])>.019
    # No undocumented TCP lever-arm compensation is performed by the SDK wrapper.
    assert policy_trace(action)['sdk_preview_mm_abc_deg'][:3]==[0.,0.,0.]


def good_status():
    return dict(header_mode='strict',inferred=True,finite=True,within_experimental_bounds=True,
                history_mask=[True]*10,reference_ns=10**9,expires_ns=1_100_000_000,
                policy_trace=policy_trace([.0002,0,0,0,0,0]))


def test_expiry_off_keeps_other_guards_and_single_use_rb():
    s=good_status()
    assert candidate_reason(s,1_105_850_000)=='expired_or_future'
    assert candidate_reason(s,1_105_850_000,candidate_expiry=False)=='ok'
    assert candidate_reason(s,999_999_999,candidate_expiry=False)=='expired_or_future'
    s['history_mask'][0]=False
    assert candidate_reason(s,2_000_000_000,candidate_expiry=False)=='history_warmup_or_gap'
    a=Arbiter(Mapping(),.1,candidate_expiry=False)
    a.select(True,False,{},.9)
    assert a.offer([.0002,0,0,0,0,0],1.,1.011)
    assert a.select(True,False,{},1.10585)[0]=='policy'
    assert a.select(True,False,{},1.20585)[0]=='paused_no_policy'
    assert a.offer([.0002,0,0,0,0,0],1.2,1.5)
    assert a.select(True,True,{},1.6)[0]=='human'
    assert a.select(True,False,{},1.7)[0]=='paused_no_policy'
    assert not a.offer([.0002,0,0,0,0,0],1.3,1.8)
    assert not a.offer([.0002,0,0,0,0,0],2.,1.8)
    assert a.offer([.0002,0,0,0,0,0],1.8,1.9)
    assert a.select(False,False,{},2.)[0]=='paused_disconnected'
    assert not a.offer([.0002,0,0,0,0,0],1.8,2.1)


@pytest.mark.parametrize('patch,reason',[
    ({'header_mode':'receive-only-diagnostic'},'diagnostic_headers'),
    ({'inferred':False},'no_finite_prediction'),({'finite':False},'no_finite_prediction'),
    ({'within_experimental_bounds':False},'experimental_bounds'),
    ({'history_mask':[False]+[True]*9},'history_warmup_or_gap'),
    ({'policy_trace':policy_trace([.002,0,0,0,0,0])},'policy_translation_speed_bound'),
    ({'policy_trace':policy_trace([0,0,0,.03,0,0])},'policy_rotation_speed_bound')])
def test_candidate_gates(patch,reason):
    s=good_status();s.update(patch);assert candidate_reason(s,1_050_000_000)==reason


def test_deadline_scale_and_no_double_conversion():
    s=good_status();assert candidate_reason(s,1_050_000_000)=='ok'
    assert candidate_reason(s,1_100_000_000)=='expired_or_future'
    assert candidate_reason(s,999_999_999)=='expired_or_future'
    t=policy_trace([0,.001,0,0,0,0],.5)
    assert t['candidate_m_rad']==[0,.0005,0,0,0,0]
    assert t['sdk_preview_mm_abc_deg']==[0,0,.5,0,0,0]
    assert not t['candidate_is_sdk_converted']
    with pytest.raises(ValueError):policy_trace([0]*6,2)


def test_launcher_preview_isolated_and_execute_uses_same_conversion(tmp_path):
    a=NS(checkpoint=tmp_path/'best.pt',output=tmp_path,duration=5,device='cpu',gamepad='/missing',
         eef_reference='raw',policy_scale=1,speed_mm_s=10,rotation_deg_s=10,execute=False)
    cmd,topic=commands(a)
    assert topic.startswith('/omi/policy/preview_') and '--publish' not in cmd[0]
    assert cmd[0][cmd[0].index('--frame')+1]=='base_link'
    assert cmd[0][cmd[0].index('--output-convention')+1]==SDK_CONVENTION
    assert '--home-button-alone' not in cmd[0]
    a.home_button_code=314;a.home_button_alone=True
    cmd,_=commands(a)
    assert cmd[0][cmd[0].index('--home-button-code')+1]=='314'
    assert '--home-button-alone' in cmd[0]
    a.execute=True;cmd,topic=commands(a)
    assert topic=='/omi/policy/candidate' and '--publish' in cmd[0]
    a.candidate_expiry='off';cmd,_=commands(a)
    for child in cmd:
        assert child[child.index('--candidate-expiry')+1]=='off'


def test_gamepad_node_imports_without_running_ros():
    from omi_hil_rl.real import gamepad_node
    assert callable(gamepad_node.main)


def test_large_live_prediction_caps_direction_and_sdk_motion():
    d=np.array([-.00182918063364923,.02401898428797722,-.024229703471064568,
                -.05923205986618996,.16863715648651123,-.014857207424938679])
    t=policy_trace(d,.5,max_translation_m=.001,max_rotation_rad=math.pi/180)
    capped=np.array(t['candidate_m_rad'])
    assert t['norm_limited']
    for original,actual,limit in ((d[:3],capped[:3],.001),(d[3:],capped[3:],math.pi/180)):
        assert np.linalg.norm(actual)==pytest.approx(limit)
        np.testing.assert_allclose(actual/np.linalg.norm(actual),original/np.linalg.norm(original))
    s=good_status();s['policy_trace']=t
    assert candidate_reason(s,1_050_000_000)=='ok'
    a=Arbiter(Mapping());a.select(True,False,{},1.)
    assert a.offer(capped,1.01,1.02)
    mode,selected=a.select(True,False,{},1.03)
    assert mode=='policy'
    wire=wire_action(selected,SDK_CONVENTION)
    assert np.linalg.norm(wire[:3])==pytest.approx(1.)
    assert Rotation.from_euler('xyz',wire[3:],degrees=True).magnitude()==pytest.approx(math.pi/180)
    s['within_experimental_bounds']=False
    assert candidate_reason(s,1_050_000_000)=='experimental_bounds'
    s['within_experimental_bounds']=True;s['history_mask'][0]=False
    assert candidate_reason(s,1_050_000_000)=='history_warmup_or_gap'


@pytest.mark.parametrize('d',[[0]*6,[.0002,0,0,.003,0,0],[.004,0,0,.003,0,0],[.0002,0,0,.04,0,0]])
def test_norm_cap_independent_and_never_amplifies(d):
    t=policy_trace(d,.5,max_translation_m=.001,max_rotation_rad=.01)
    scaled=np.array(d)*.5;actual=np.array(t['candidate_m_rad'])
    for before,after,limit in ((scaled[:3],actual[:3],.001),(scaled[3:],actual[3:],.01)):
        if np.linalg.norm(before)<=limit:np.testing.assert_array_equal(after,before)
        else:assert np.linalg.norm(after)==pytest.approx(limit)


@pytest.mark.parametrize('limit',[0,-1,float('nan'),float('inf')])
def test_norm_cap_invalid_limit(limit):
    with pytest.raises(ValueError):policy_trace([0]*6,max_translation_m=limit,max_rotation_rad=.01)
