import numpy as np
import torch
from omi_hil_rl.training.eef_bc_history import history_indices,HistoryPolicy
from omi_hil_rl.training.eef_bc_grid import GridProfile


def test_exact_causal_slots_with_gaps_and_episode_reset():
    times=np.array([0,100,300,400])*1_000_000+10**9
    ix=history_indices(times)
    assert ix[0,-1]==0 and np.all(ix[0,:-1]==-1)
    assert ix[2,-1]==2 and ix[2,-2]==-1 and ix[2,-3]==1
    for row,t in zip(ix,times):assert np.all(times[row[row>=0]]<=t)
    assert np.all(history_indices(times+10**10)[0,:-1]==-1)


def test_masked_history_no_influence_and_history_has_gradient():
    torch.manual_seed(7);m=HistoryPolicy(GridProfile().CONTRACT).eval()
    f=torch.randn(2,10,128,requires_grad=True);mask=torch.ones(2,10,dtype=torch.bool);mask[:,3]=False
    y=m.from_features(f,mask)
    changed=f.detach().clone();changed[:,3]=1000
    torch.testing.assert_close(y,m.from_features(changed,mask),rtol=0,atol=0)
    y.sum().backward()
    assert torch.count_nonzero(f.grad[:,3])==0
    assert torch.count_nonzero(f.grad[:,0])>0
