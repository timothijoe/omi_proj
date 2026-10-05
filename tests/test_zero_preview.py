"""Diagnostic real sensors must not masquerade as accepted human-command demos."""
import json
import numpy as np
import pytest
from omi_hil_rl.training.zero_preview import load_step, VERSION
from omi_hil_rl.training.demo_bc import make_plan


def test_zero_placeholder_guards_and_training_rejection(tmp_path):
    ep=tmp_path/'episodes'/'zero_preview';ep.mkdir(parents=True)
    manifest=dict(version=VERSION,count=1,keep=True,valid=True,synthetic=False)
    (ep/'demo.json').write_text(json.dumps(manifest))
    meta=dict(action_source='zero_placeholder',observation_time_ns=100,next_observation_time_ns=100000100)
    def write(action):
        np.savez_compressed(ep/'000000.npz',executed_action=action,action_m_rad=np.zeros(6,np.float32),metadata=np.asarray(json.dumps(meta)))
    write(np.zeros(6,np.float32))
    assert np.all(load_step(ep,0,manifest)[2]==0)
    with pytest.raises(ValueError,match='unsupported demo schema'):
        make_plan([tmp_path],tmp_path/'plan.json')
    write(np.ones(6,np.float32))
    with pytest.raises(ValueError,match='zero placeholder'):load_step(ep,0,manifest)
    meta['next_observation_time_ns']+=1;write(np.zeros(6,np.float32))
    with pytest.raises(ValueError,match='exactly 100ms'):load_step(ep,0,manifest)
