from types import SimpleNamespace as NS

import numpy as np
import pytest
import torch

from omi_hil_rl.training.demo_wrench import align_history
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.wrench_live import WrenchObservations, infer_wrench_window, load_wrench_policy
from omi_hil_rl.real.policy_gamepad import commands
from omi_hil_rl.real.gamepad_control import Arbiter, Mapping


def wrench(t, side='a', value=1., frame=None, stamp=None):
    stamp = t if stamp is None else stamp
    return NS(header=NS(stamp=NS(sec=stamp//10**9, nanosec=stamp%10**9),
                        frame_id=frame or 'tactile_'+side),
              wrench=NS(force=NS(x=value,y=2.,z=3.), torque=NS(x=4.,y=5.,z=6.)))


def runtime():
    r = WrenchObservations(GridProfile('required').CONTRACT)
    r.profile.decode = lambda k,m: (m.stamp,m.value)
    return r


def feed(r,t):
    for key in r.topics.values():
        if key.startswith('wrench_'):
            assert r.ingest(key,wrench(t,key[-1]),t)
            continue
        if key in ('rgb','wrist_rgb'):value=np.full((3,128,128),42,np.uint8)
        elif key=='eef':value=np.array([.5,.1,.8,0,0,0,1],np.float32)
        else:value=np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32)
        assert r.ingest(key,NS(stamp=t,value=value),t)


def warm(r):
    for i in range(10):
        t=10**9+i*100_000_000
        feed(r,t)
        window,status=r.window(t)
    return t,window,status


def test_live_history_matches_offline_alignment_and_has_no_joints():
    r=runtime();t,window,status=warm(r)
    assert window is not None and all(status['history_mask'])
    data,mask=window
    expected,_=align_history(r.wrenches,t)
    np.testing.assert_array_equal(data['wrench'],expected['wrench'])
    assert data['wrench'].shape==(10,2,6) and data['wrench_mask'].all()
    assert not data['state'][:,:7].any()
    # Receiving a future sample does not use it in an earlier history slot.
    r.ingest('wrench_a',wrench(t+50_000_000,value=99),t+50_000_000)
    aligned,_=align_history(r.wrenches,t)
    assert aligned['wrench'][-1,0,0]==1


@pytest.mark.parametrize('bad',[
    dict(value=float('nan')),dict(frame='wrong'),dict(stamp=1),dict(stamp=9_000_000_000)])
def test_invalid_newest_blocks_no_fallback(bad):
    r=runtime();t,_,_=warm(r)
    assert not r.ingest('wrench_a',wrench(t+1,**bad),t+1)
    assert r.window(t+100_000_000)[0] is None


def test_missing_stale_reset_and_recovery():
    r=runtime();t,_,_=warm(r)
    r.wrenches['b'].clear()
    assert r.window(t+100_000_000)[0] is None
    r=runtime();t,_,_=warm(r)
    for i in range(1,5):
        stamp=t+i*100_000_000
        # Keep other inputs fresh, but stop wrench B.
        saved=r.topics
        r.topics={k:v for k,v in saved.items() if v!='wrench_b'}
        feed(r,stamp);r.topics=saved
        window,status=r.window(stamp)
    assert window is None and status['reason']=='incomplete_or_invalid_wrench_history'
    for i in range(5,18):
        stamp=t+i*100_000_000;feed(r,stamp);window,status=r.window(stamp)
    assert window is not None and window[1].all()
    r.ingest('wrench_a',wrench(1_000_000_000),1_000_000_000)
    assert not r.wrenches['b'] and not r.history


def test_strict_training_input_required():
    for mode,ref in [('receive-only-diagnostic','raw'),('strict','bag-baseline-v1')]:
        with pytest.raises(ValueError):WrenchObservations(GridProfile('required').CONTRACT,mode,ref)


def test_deterministic_inference_uses_contract_scale_once():
    class Actor:
        physical_action_scale=np.array([.0005]*3+[np.deg2rad(.5)]*3)
        def sample(self,obs,deterministic):
            assert deterministic and obs['history_mask'].shape==(1,10)
            assert obs['wrench'].shape==(1,10,2,6)
            return torch.tensor([[1.,-.5,0,0,0,.25]]),None
    _,window,_=warm(runtime())
    action,ms=infer_wrench_window(Actor(),{},window,torch.device('cpu'))
    np.testing.assert_allclose(action,[.0005,-.00025,0,0,0,np.deg2rad(.125)])
    assert ms>=0


def test_wrong_checkpoint_fails_before_ros(tmp_path):
    path=tmp_path/'actor.pt'
    torch.save(dict(contract={},recipe={}),path)
    with pytest.raises(ValueError):load_wrench_policy(path,'cpu')


def test_launcher_and_rb_precedence_with_wrench_policy(tmp_path):
    a=NS(checkpoint=tmp_path/'actor.pt',output=tmp_path,duration=5,device='cpu',gamepad='/missing',
         eef_reference='raw',policy_scale=.1,speed_mm_s=5,rotation_deg_s=5,execute=False,
         model_kind='passive-wrench-bc',home_button_code=307)
    cmd,topic=commands(a)
    assert topic.startswith('/omi/policy/preview_') and '--publish' not in cmd[0]
    assert cmd[1][cmd[1].index('--model-kind')+1]=='passive-wrench-bc'
    arb=Arbiter(Mapping(),.1)
    arb.select(True,False,{},1.)
    assert arb.offer([.0001,0,0,0,0,0],1.01,1.02)
    mode,action=arb.select(True,True,{},1.03)
    assert mode=='human' and not action.any()
    assert arb.select(True,False,{},1.04)[0]=='paused_no_policy'
    assert not arb.offer([.0001,0,0,0,0,0],1.02,1.05)
    assert arb.offer([.0001,0,0,0,0,0],1.06,1.07)
    assert arb.select(True,False,{},1.08)[0]=='policy'
    assert arb.select(False,False,{},1.09)[0]=='paused_disconnected'
