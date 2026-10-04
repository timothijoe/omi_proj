from types import SimpleNamespace as NS
import numpy as np
import pytest
import torch
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.eef_bc_wrench import WrenchBank,WrenchProfile,validate_wrench
from omi_hil_rl.training.eef_bc_policy import normalization,inputs
from omi_hil_rl.training.eef_bc_history import HistoryPolicy,VERSION,SLOTS,PERIOD_NS,history_indices,predictions,load_history
from omi_hil_rl.training.eef_history_online import OnlineHistoryPolicy


def dataset(profile,n=12):
    rng=np.random.default_rng(31)
    d=dict(rgb=rng.integers(0,255,(n,3,128,128),dtype=np.uint8),
        wrist_rgb=np.zeros((n,3,128,128),np.uint8),camera_mask=np.tile(np.array([1,0],np.float32),(n,1)),
        tactile=rng.normal(size=(n,10,16,24)).astype(np.float32),state=np.zeros((n,14),np.float32),
        action=np.zeros((n,6),np.float32))
    d['state'][:,-1]=1
    if 'wrench_shape' in profile.CONTRACT:
        d.update(wrench=np.zeros((n,12),np.float32),wrench_mask=np.zeros((n,2),np.float32),wrench_enabled=np.ones((n,2),np.float32))
    return d


def checkpoint(path,profile,data):
    torch.manual_seed(5);model=HistoryPolicy(profile.CONTRACT).eval();norm=normalization(data)
    torch.save(dict(config=dict(version=VERSION,history_slots=SLOTS,period_ns=PERIOD_NS,
        base_contract=profile.CONTRACT,normalization=norm),state_dict=model.state_dict()),path)
    return model,norm


def test_wrench_validity_and_disabled_nonzero():
    bank=WrenchBank((0,1));t=10**9
    bank.add(0,t,np.ones(6));bank.add(1,t,np.zeros(6))
    d,_,reason=bank.at(t)
    assert d['wrench'].sum()==0 and d['wrench_mask'].tolist()==[0,1]
    assert reason==['disabled','valid']  # zero is a valid measurement when enabled
    bank.add(1,t+1,np.full(6,np.nan));d,_,reason=bank.at(t+1)
    assert d['wrench_mask'].tolist()==[0,0] and reason[1]=='invalid'
    bank.add(1,t+2,np.ones(6),valid=False)
    assert bank.at(t+2)[2][1]=='invalid'
    bank.add(1,t+3,np.ones(6))
    assert bank.at(t+250_000_004)[2][1]=='stale'
    assert bank.at(t-1)[2][1]=='missing'


def test_nonfinite_ros_wrench_becomes_masked():
    v=NS(x=float('nan'),y=0.,z=0.)
    msg=NS(header=NS(stamp=NS(sec=1,nanosec=0)),wrench=NS(force=v,torque=v))
    t,value=WrenchProfile().decode('a_wrench',msg)
    assert t==10**9 and not value.any()


def test_normalization_ignores_invalid_and_masks_again():
    p=WrenchProfile();d=dataset(p,3)
    d['wrench'][0,:6]=8;d['wrench_mask'][0,0]=1
    d['wrench_enabled'][1:]=0
    norm=normalization(d)
    assert norm['wrench_valid_counts']==[1,0]
    x=inputs(d,norm)
    assert torch.count_nonzero(x[-2][1:])==0
    assert norm['wrench_mean'][0][:6]==[8]*6
    bad={**d,'wrench':np.ones((3,12),np.float32)}
    with pytest.raises(ValueError):validate_wrench(bad)
    # Both enabled and disabled records share the schema.
    assert WrenchProfile(enabled=(1,1)).CONTRACT==WrenchProfile(enabled=(0,0)).CONTRACT


@pytest.mark.parametrize('wrench',[False,True])
def test_online_matches_batch_with_gaps_and_reset(tmp_path,wrench):
    torch.set_num_threads(2)
    p=WrenchProfile(enabled=(1,1)) if wrench else GridProfile();d=dataset(p)
    model,norm=checkpoint(tmp_path/'policy.pt',p,d)
    live=OnlineHistoryPolicy(tmp_path/'policy.pt',(1,1) if wrench else (0,0))
    times=(np.array([0,1,2,4,5,6,7,8,9,10,11,14])*PERIOD_NS+10**9)
    ix=history_indices(times)
    expected=predictions(model,inputs(d,norm),torch.as_tensor(ix),norm)
    actual=[]
    for i,t in enumerate(times):
        r=live.push(int(t),{k:d[k][i] for k in p.ARRAYS})
        assert r['valid'];assert r['history_mask']==(ix[i]>=0).tolist()
        actual.append(r['action'])
    np.testing.assert_allclose(actual,expected,atol=1e-8,rtol=1e-5)
    r=live.push(int(times[-1]+PERIOD_NS),None)
    assert not r['valid'] and r['action'] is None and not r['history_mask'][-1]
    live.reset();r=live.push(int(times[0]),{k:d[k][0] for k in p.ARRAYS})
    assert sum(r['history_mask'])==1
    if wrench:
        live.set_wrench_enabled((0,0));assert not live.features and live.last_reference is None
    else:
        with pytest.raises(ValueError,match='no wrench'):live.set_wrench_enabled((1,0))


def test_future_and_off_grid_rejected(tmp_path):
    p=GridProfile();d=dataset(p);checkpoint(tmp_path/'p.pt',p,d);live=OnlineHistoryPolicy(tmp_path/'p.pt')
    obs={k:d[k][0] for k in p.ARRAYS}
    with pytest.raises(ValueError,match='Future'):live.push(10**9,obs,source_stamps={'eef':10**9+1})
    live.push(10**9,obs)
    with pytest.raises(ValueError,match='Off-grid'):live.push(10**9+1,obs)
    live.step(10**9-1)
    assert live.epoch==1 and not live.features


def test_v4_history_uses_unlabeled_observations(tmp_path):
    import json
    from omi_hil_rl.training.eef_bc_data import sha256
    p=WrenchProfile();pool=dataset(p,4);times=10**9+np.arange(4)*PERIOD_NS
    selected=[1,3]
    np.savez_compressed(tmp_path/'samples.npz',**{k:v[selected] for k,v in pool.items()},
        reference_ns=times[selected],source_ns=times[selected,None])
    np.savez_compressed(tmp_path/'history_observations.npz',**{k:pool[k] for k in p.ARRAYS},
        reference_ns=times,source_ns=times[:,None])
    (tmp_path/'manifest.json').write_text(json.dumps(dict(contract=p.CONTRACT,episode_id='test',
        samples_sha256=sha256(tmp_path/'samples.npz'),history_observations_sha256=sha256(tmp_path/'history_observations.npz'))))
    data,_,ix,_,_=load_history([tmp_path])
    assert len(data['action'])==2 and len(data['state'])==4
    assert ix[1,-4:].tolist()==[0,1,2,3]
    norm=normalization(data)
    pred=predictions(HistoryPolicy(p.CONTRACT).eval(),inputs(data,norm),torch.as_tensor(ix),norm)
    assert pred.shape==(2,6)


def test_ingress_guard_supersedes_good_wrench_and_mode_resets(tmp_path):
    p=WrenchProfile(enabled=(1,1));d=dataset(p);checkpoint(tmp_path/'p.pt',p,d)
    live=OnlineHistoryPolicy(tmp_path/'p.pt',(1,1))
    v=NS(x=1.,y=2.,z=3.);msg=NS(header=NS(stamp=NS(sec=1,nanosec=0)),wrench=NS(force=v,torque=v))
    live.ingest('a_wrench',msg,10**9)
    assert live.buffer.bank.at(10**9)[0]['wrench_mask'].tolist()==[1,0]
    live.ingest('a_wrench',msg,10**9+1,source_valid=False)
    assert not live.buffer.bank.at(10**9+1)[0]['wrench'].any()
    # Old header cannot become a fresh valid measurement just by arriving again.
    live.ingest('a_wrench',msg,2*10**9)
    assert not live.buffer.bank.at(2*10**9)[0]['wrench_mask'].any()
    msg.header.stamp.sec=0
    live.ingest('a_wrench',msg,2*10**9+1)
    assert not live.buffer.bank.at(2*10**9+1)[0]['wrench'].any()
    live.set_wrench_enabled((0,0))
    assert live.epoch==1 and not live.buffer.bank.data[0]
