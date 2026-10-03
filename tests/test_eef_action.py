import json
from types import SimpleNamespace as Obj
import numpy as np
import pytest
from omi_hil_rl.training import eef_action as a
from omi_hil_rl.training import eef_bc_data as d

IDENTITY=np.array([0.,0.,0.,0.,0.,0.,1.])


def test_zero_known_translation_and_base_rotation_order():
    np.testing.assert_allclose(a.apply(IDENTITY,np.zeros(6)),IDENTITY)
    current=np.r_[[1.,2.,3.],a.from_rotvec([np.pi/2,0,0])]
    action=np.array([.01,-.02,.03,0,0,np.pi/2])
    target=a.apply(current,action)
    np.testing.assert_allclose(target[:3],[1.01,1.98,3.03])
    np.testing.assert_allclose(target[3:],[.5,.5,.5,.5],atol=1e-14)
    np.testing.assert_allclose(a.between(current,target),action,atol=1e-14)
    right=a.multiply(current[3:],a.from_rotvec(action[3:]))
    assert not np.allclose(target[3:],right)
    # Current-state anchor differs from previous-target accumulation.
    previous=a.apply(current,[.02,0,0,0,0,0])
    assert not np.allclose(a.apply(previous,action),target)


def test_random_roundtrip_and_quaternion_sign_equivalence():
    rng=np.random.default_rng(4)
    for _ in range(200):
        q=rng.normal(size=4); q/=np.linalg.norm(q)
        current=np.r_[rng.normal(size=3),q]
        action=rng.normal(size=6)*.1
        target=a.apply(current,action)
        np.testing.assert_allclose(a.between(current,target),action,atol=2e-14)
        opposite=target.copy(); opposite[3:]*=-1
        np.testing.assert_allclose(a.between(current,opposite),action,atol=2e-14)
    for axis in np.eye(3):
        q=np.r_[axis,0.]
        np.testing.assert_allclose(a.rotvec(q),a.rotvec(-q),atol=1e-14)
        np.testing.assert_allclose(a.rotvec(q),axis*np.pi,atol=1e-14)


@pytest.mark.parametrize('bad',[[0,0,0,0],[0,0,0,2],[np.nan,0,0,1]])
def test_invalid_quaternion(bad):
    with pytest.raises(ValueError): a.quaternion(bad)


def test_reject_bounds_without_clipping():
    original=np.array([.06,0,0,0,0,0.])
    with pytest.raises(ValueError,match='translation_bound'):a.check_increment(original,.05,.25)
    assert original[0]==.06
    with pytest.raises(ValueError,match='rotation_bound'):a.check_increment([0,0,0,.3,0,0],.05,.25)
    with pytest.raises(ValueError):a.apply(IDENTITY,[0,0,0,4,0,0])
    with pytest.raises(ValueError):a.check_increment(np.zeros(6),0,.25)


def fill(buf,t):
    for key in d.legacy.KEYS:
        if key=='rgb': v=np.zeros((3,128,128),np.uint8)
        elif key=='q':v=np.zeros(7,np.float32)
        elif key.endswith('force'):v=np.zeros(6,np.float32)
        else:v=np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32)
        buf.add(key,t,v)


def test_causal_eef_expiry_reset_frame_and_bounded_history():
    b=d.ObservationBuffer(); t=10**9; fill(b,t)
    with pytest.raises(d.NotReady,match='missing:eef'):b.at(t)
    b.add('eef',t,IDENTITY)
    obs,stamps=b.at(t)
    assert obs['state'].shape==(26,) and stamps['eef']==t
    b.add('eef',t+100_000_000,IDENTITY+np.array([.01,0,0,0,0,0,0]))
    np.testing.assert_array_equal(b.at(t)[0]['state'],obs['state'])
    with pytest.raises(d.NotReady,match='stale:eef'):b.at(t+50_000_001)
    with pytest.raises(ValueError):b.add('eef',t,IDENTITY)
    b.clear()
    with pytest.raises(d.NotReady):b.at(t)
    for i in range(1000):b.add('eef',t+i,IDENTITY)
    assert len(b.eef)==128
    msg=Obj(header=Obj(frame_id='tool',stamp=Obj(sec=1,nanosec=0)))
    with pytest.raises(ValueError,match='frame'):d.decode('eef',msg)
    assert all(not k.startswith('/tj/control/') for k in d.TOPICS)
    assert d.CONTRACT!=d.legacy.CONTRACT


def test_future_proxy_timing_gaps_missing_and_jump():
    t=10**9; stamps=[t+i*10_000_000 for i in range(14)]
    poses=[a.apply(IDENTITY,[i*.001,0,0,0,0,0]) for i in range(14)]
    delta,target,selected=d.label_for(t+3_000_000,t,IDENTITY,stamps,poses)
    assert selected==t+110_000_000
    np.testing.assert_allclose(delta,[.011,0,0,0,0,0])
    with pytest.raises(d.NotReady,match='missing_future'):d.label_for(t+100_000_000,t,IDENTITY,stamps,poses)
    with pytest.raises(d.NotReady,match='time_gap'):d.label_for(t,t,IDENTITY,[t,t+100_000_000],[IDENTITY,poses[-1]])
    poses[10]=a.apply(IDENTITY,[.06,0,0,0,0,0])
    with pytest.raises(d.NotReady,match='translation_bound'):d.label_for(t,t,IDENTITY,stamps,poses)
    with pytest.raises(ValueError,match='accept-future'):d.export('unused','unused')


def make_dataset(path,identity='one'):
    path.mkdir(); rng=np.random.default_rng(7)
    state=rng.normal(size=(12,26)).astype(np.float32)*.1
    state[:,-7:]=IDENTITY
    data=dict(rgb=rng.integers(0,256,(12,3,128,128),dtype=np.uint8),
              tactile=rng.normal(size=(12,10,16,24)).astype(np.float32)*.1,
              state=state,action=rng.normal(size=(12,6)).astype(np.float32)*.003)
    np.savez_compressed(path/'samples.npz',**data)
    (path/'manifest.json').write_text(json.dumps(dict(contract=d.CONTRACT,samples_sha256=d.sha256(path/'samples.npz'),episode_id=identity)))
    return data


def test_eef_training_reload_contract_and_episode_separation(tmp_path):
    pytest.importorskip('torch')
    from omi_hil_rl.training import eef_bc_policy as p
    from omi_hil_rl.training.bc_policy import load_policy as old_load
    data=make_dataset(tmp_path/'train')
    make_dataset(tmp_path/'duplicate')
    with pytest.raises(ValueError):p.train([tmp_path/'train'],tmp_path/'no_mode',steps=1)
    with pytest.raises(ValueError):p.train([tmp_path/'train'],tmp_path/'leak',val_paths=[tmp_path/'duplicate'],steps=1)
    report=p.train([tmp_path/'train'],tmp_path/'model',overfit=True,steps=40)
    assert report['final']['translation_rmse_m']<report['initial']['translation_rmse_m']
    assert report['final']['rotation_rmse_rad']<report['initial']['rotation_rmse_rad']
    model,norm,cp=p.load_policy(tmp_path/'model/policy.pt')
    with np.load(tmp_path/'model/train_predictions.npz') as saved:
        np.testing.assert_array_equal(p.predict(model,norm,data),saved['prediction'])
    with pytest.raises(ValueError,match='Incompatible'):old_load(tmp_path/'model/policy.pt')
    assert report['validation'] is None
    val=make_dataset(tmp_path/'val','two')
    val['state'][:,:19]+=20
    np.savez_compressed(tmp_path/'val/samples.npz',**val)
    m=json.loads((tmp_path/'val/manifest.json').read_text());m['samples_sha256']=d.sha256(tmp_path/'val/samples.npz')
    (tmp_path/'val/manifest.json').write_text(json.dumps(m))
    report=p.train([tmp_path/'train'],tmp_path/'held_out',val_paths=[tmp_path/'val'],steps=1)
    assert report['normalization']==p.normalization(data)


def test_typed_proposal_roundtrip_when_ros_available():
    pytest.importorskip('omi_action_msgs.msg')
    from rclpy.serialization import serialize_message,deserialize_message
    from omi_action_msgs.msg import EefActionProposal
    from omi_hil_rl.training.eef_bc_output import proposal_values,message
    obs=dict(state=np.r_[np.zeros(19),IDENTITY])
    row=dict(epoch=2,reference_ns=1_100_000_000,source_stamps={'eef':1_099_000_000},
             **proposal_values(np.array([.01,0,0,0,.02,0]),obs))
    m=deserialize_message(serialize_message(message(row,2_000_000_000)),EefActionProposal)
    assert m.shadow_only and m.valid and m.source=='POLICY'
    assert m.header.frame_id=='base_link' and m.anchor_stamp.nanosec==99_000_000
    assert m.translation.x==.01 and m.rotation_vector.y==.02
    assert m.proposed_pose.position.x==.01 and m.horizon.nanosec==100_000_000
