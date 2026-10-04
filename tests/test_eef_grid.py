from types import SimpleNamespace as NS
import numpy as np
import pytest
from omi_hil_rl.training.eef_bc_grid import GridProfile
from omi_hil_rl.training.eef_bc_data import profile_for, NotReady


def message(a, encoding):
    return NS(height=a.shape[0],width=a.shape[1],encoding=encoding,is_bigendian=False,
        step=a.strides[0],data=a.tobytes(),header=NS(stamp=NS(sec=1,nanosec=0)))


def test_grid_no_repool_or_recrop():
    p=GridProfile()
    a=np.arange(16*24*2,dtype=np.float32).reshape(16,24,2)
    stamp,value=p.decode('a_deformation',message(a,'32FC2'))
    assert stamp==10**9
    np.testing.assert_array_equal(value,a.transpose(2,0,1))
    rgb=np.zeros((128,128,3),np.uint8);rgb[0,0]=[1,2,3];rgb[-1,-1]=[4,5,6]
    _,value=p.decode('wrist_rgb',message(rgb,'bgr8'))
    np.testing.assert_array_equal(value,rgb[:,:,::-1].transpose(2,0,1))
    with pytest.raises(ValueError):p.decode('a_deformation',message(np.zeros((288,384,2),np.float32),'32FC2'))


def test_no_wrench_state_and_causal_expiry():
    p=GridProfile();b=p.ObservationBuffer();t=10**9
    for key in p.KEYS:
        if key=='wrist_rgb':continue
        value=(np.zeros((3,128,128),np.uint8) if key=='rgb' else
               np.zeros(7,np.float32) if key=='q' else
               np.array([0,0,0,0,0,0,1.]) if key=='eef' else
               np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32))
        b.add(key,t,value)
    obs,stamps=b.at(t)
    assert obs['state'].shape==(14,)
    assert obs['tactile'].shape==(10,16,24)
    np.testing.assert_array_equal(obs['camera_mask'],[1,0])
    b.add('wrist_rgb',t+1,np.ones((3,128,128),np.uint8))
    assert b.at(t)[1]['wrist_rgb']==0
    assert b.at(t+1)[1]['wrist_rgb']==t+1
    with pytest.raises(NotReady):b.at(t+51_000_000)
    assert profile_for(p.CONTRACT).CONTRACT==p.CONTRACT
    bad=dict(p.CONTRACT,state_shape=[26])
    with pytest.raises(ValueError):profile_for(bad)


def test_v3_policy_forward_only_and_no_shadow():
    import torch
    from omi_hil_rl.training.eef_bc_policy import Policy
    from omi_hil_rl.training.bc_shadow import profile_modules
    p=GridProfile();model=Policy(p.CONTRACT).eval()
    with torch.inference_mode():
        y=model(torch.zeros(2,3,128,128),torch.zeros(2,10,16,24),torch.zeros(2,14),
                torch.zeros(2,3,128,128),torch.tensor([[1.,0.],[1.,1.]]))
    assert y.shape==(2,6)
    with pytest.raises(ValueError,match='offline-only'):profile_modules('eef',p.CONTRACT)
