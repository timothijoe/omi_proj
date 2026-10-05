import json
import numpy as np
import pytest
from omi_hil_rl.training.passive_preview import VERSION,commands_between,load_step
from omi_hil_rl.training.demo_bc import make_plan


def test_command_window_boundaries_do_not_reuse_or_include_future():
    rows=[dict(bag_receive_ns=t,wire_action=[t]*6) for t in (9,10,19,20,21)]
    assert [r['bag_receive_ns'] for r in commands_between(rows,10,20)]==[10,19]
    assert [r['bag_receive_ns'] for r in commands_between(rows,20,21)]==[20]
    assert commands_between(rows,30,40)==[]


def test_passive_wire_preserves_values_and_rejects_bad_timing(tmp_path):
    manifest=dict(version=VERSION,count=1)
    wire=np.array([.5,-.2,.1,0,.4,0],np.float64)
    meta=dict(observation_time_ns=1,next_observation_time_ns=100000001,
              command_audit=dict(command_receive_ns=100,wire_action=wire.tolist()))
    def write():np.savez_compressed(tmp_path/'000000.npz',recorded_wire_action=wire,metadata=np.asarray(json.dumps(meta)))
    write();np.testing.assert_array_equal(load_step(tmp_path,0,manifest)[2],wire)
    meta['command_audit']['command_receive_ns']=100000001;write()
    with pytest.raises(ValueError,match='timing'):load_step(tmp_path,0,manifest)
    meta['command_audit']['command_receive_ns']=100;meta['command_audit']['wire_action']=[0]*6;write()
    with pytest.raises(ValueError,match='mismatch'):load_step(tmp_path,0,manifest)


def test_unverified_wire_is_not_accepted_command_training_data(tmp_path):
    (tmp_path/'demo.json').write_text(json.dumps(dict(version=VERSION,count=1)))
    with pytest.raises(ValueError,match='unsupported demo schema'):
        make_plan([tmp_path],tmp_path/'plan.json')
