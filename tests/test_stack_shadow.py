from types import SimpleNamespace as NS
import numpy as np
import pytest

from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.stack_shadow import StackObservations


def runtime():
    r=StackObservations(GridProfile('required').CONTRACT)
    r.profile.decode=lambda k,m:(m.stamp,m.value)
    return r


def feed(r,t):
    for key in r.topics.values():
        if key in ('rgb','wrist_rgb'):value=np.full((3,128,128),42,np.uint8)
        elif key=='eef':value=np.array([.5,.1,.8,0,0,0,1],np.float32)
        else:value=np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32)
        assert r.ingest(key,NS(stamp=t,value=value),t)


def test_no_joint_dependency_and_exact_missing_history_slots():
    r=runtime();t=10**9
    assert 'q' not in r.topics.values()
    feed(r,t);w,s=r.window(t)
    assert s['history_mask']==[False]*9+[True]
    assert np.all(w[0]['state'][:,:7]==0)
    assert s['camera_mask']==[1,1]
    # Skip two decisions: preserve gaps instead of compacting old observations.
    feed(r,t+300_000_000);w,s=r.window(t+300_000_000)
    assert s['history_mask']==[False]*6+[True,False,False,True]
    assert w[0]['rgb'].shape==(10,3,128,128)
    assert w[0]['tactile'].shape==(10,10,16,24)
    assert 'q' not in s['source_receive_ns']


def test_stale_future_and_invalid_do_not_reuse_previous_sample():
    r=runtime();t=10**9;feed(r,t)
    w,s=r.window(t+60_000_000)
    assert w is None and s['reason']=='missing_or_stale:eef'
    r=runtime();feed(r,t)
    assert not r.ingest('eef',NS(stamp=t+200_000_000,value=np.zeros(7)),t+1)
    assert r.window(t+1)[0] is None
    assert r.rejected['eef:header_ahead']==1
    r=runtime();feed(r,t)
    def bad(k,m):raise ValueError('frame mismatch')
    r.profile.decode=bad
    assert not r.ingest('eef',NS(),t+1)
    assert r.window(t+1)[0] is None


def test_receive_clock_reset_and_off_grid_reference():
    r=runtime();feed(r,2*10**9);r.window(2*10**9)
    with pytest.raises(ValueError,match='lattice'):r.window(2*10**9+1)
    feed(r,10**9)
    _,s=r.window(10**9)
    assert s['epoch']==1 and sum(s['history_mask'])==1


def test_training_decoder_used_for_eef_frame_and_quaternion():
    r=StackObservations(GridProfile('required').CONTRACT)
    m=NS(header=NS(frame_id='A_base',stamp=NS(sec=1,nanosec=0)),
         pose=NS(position=NS(x=0,y=0,z=0),orientation=NS(x=0,y=0,z=0,w=1)))
    assert not r.ingest('eef',m,10**9)
    assert r.latest['eef']['reason']=='EEF frame mismatch'


def test_diagnostic_mode_bypasses_header_age_only():
    r=runtime();r.header_mode='receive-only-diagnostic';t=10**9
    feed(r,t)
    pose=np.array([.5,.1,.8,0,0,0,1],np.float32)
    assert r.ingest('eef',NS(stamp=t+500_000_000,value=pose),t)
    _,s=r.window(t)
    assert not s['training_header_guards_enforced'] and not s['execution_allowed']
    assert r.latest['eef']['header_age_ms']==-500
    w,s=r.window(t+100_000_000)
    assert w is None and s['reason']=='missing_or_stale:eef'
