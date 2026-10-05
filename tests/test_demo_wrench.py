import numpy as np
from omi_hil_rl.training.demo_wrench import align_history


def test_wrench_alignment_is_causal_masked_and_preserves_headers():
    t=2_000_000_000
    a=np.arange(6,dtype=np.float32)
    records={'a':[(t-50_000_000,t-60_000_000,a,'finger_a'),(t+1,t,a+100,'future')],
             'b':[(t-250_000_001,t-260_000_001,a,'stale')]}
    data,frames=align_history(records,t)
    np.testing.assert_array_equal(data['wrench'][-1,0],a)
    assert data['wrench_mask'][-1].tolist()==[1,0]
    assert data['wrench_mask'][0].tolist()==[0,0]
    assert data['wrench_receive_ns'][-1,0]==t-50_000_000
    assert data['wrench_header_ns'][-1,0]==t-60_000_000
    assert frames[-1]==['finger_a','stale']
    assert np.all(data['wrench'][-1,1]==0) # storage placeholder, masked out
    records['a'].insert(1,(t,t,np.full(6,np.nan),'invalid'))
    data,_=align_history(records,t)
    assert not data['wrench_mask'][-1,0] # do not silently fall back past bad latest data
