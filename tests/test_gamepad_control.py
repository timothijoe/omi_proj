import math
import numpy as np
import pytest
from omi_hil_rl.real.gamepad_control import Mapping, Arbiter, wire_action
from omi_hil_rl.real.linux_gamepad import LinuxGamepad


@pytest.mark.parametrize('axis,value,index,sign', [
    (4,-1,0,1),(3,-1,1,1),(17,-1,2,1),(0,1,3,1),(1,-1,4,1),(16,-1,5,1),
    (4,1,0,-1),(17,1,2,-1),(16,1,5,-1)])
def test_six_axes(axis,value,index,sign):
    d = Mapping().action({axis:value})
    expected = np.zeros(6)
    expected[index] = sign*(.001 if index < 3 else math.radians(1))
    np.testing.assert_allclose(d, expected)


def test_deadzone_and_combined_speed():
    m = Mapping()
    np.testing.assert_array_equal(m.action({0:.1, 4:-.14}), np.zeros(6))
    d = m.action({0:1,1:-1,3:-1,4:-1,16:-1,17:-1})
    assert np.linalg.norm(d[:3]) == pytest.approx(.001)
    assert np.linalg.norm(d[3:]) == pytest.approx(math.radians(1))
    assert wire_action([.001,0,0,0,0,math.pi/180]) == pytest.approx([1,0,0,0,0,1])


def test_hold_neutral_release_requires_new_policy():
    a = Arbiter(Mapping())
    a.select(True,False,{},1)
    assert a.offer([.001,0,0,0,0,0],1.01,1.02)
    assert a.select(True,True,{},1.03)[0] == 'human'
    assert a.select(True,True,{},1.04)[1].tolist() == [0]*6
    a.offer([.001,0,0,0,0,0],1.05,1.06)
    assert a.select(True,False,{},1.07)[0] == 'paused_no_policy'
    assert not a.offer([.001,0,0,0,0,0],1.06,1.08)
    assert a.offer([.001,0,0,0,0,0],1.08,1.09)
    assert a.select(True,False,{},1.1)[0] == 'policy'
    assert a.select(True,False,{},1.11)[0] == 'paused_no_policy'


def test_disconnect_invalidates_input_and_policy():
    a = Arbiter(Mapping())
    a.select(True,True,{4:-1},1)
    mode,d = a.select(False,True,{4:-1},1.1)
    assert mode == 'paused_disconnected'
    assert not d.any()
    a.offer([0]*6,1.11,1.12)
    assert a.select(True,False,{},1.13)[0] == 'paused_no_policy'


@pytest.mark.parametrize('action,stamp', [([float('nan')]*6,1.1),([0]*5,1.1),
    ([.002,0,0,0,0,0],1.1),([0,0,0,.1,0,0],1.1),([0]*6,.5),([0]*6,2)])
def test_reject_bad_policy(action,stamp):
    a=Arbiter(Mapping());a.select(True,False,{},1)
    assert not a.offer(action,stamp,1.2)
    assert a.select(True,False,{},1.2)[0] == 'paused_no_policy'


def test_policy_expires_before_use():
    a=Arbiter(Mapping());a.select(True,False,{},1)
    assert a.offer([0]*6,1.1,1.1)
    assert a.select(True,False,{},1.4)[0] == 'paused_no_policy'


def test_missing_device_is_disconnected(tmp_path):
    pad=LinuxGamepad(str(tmp_path/'missing'))
    pad.axes[4]=-1
    pad.buttons[311]=True
    assert not pad.poll()
    assert not pad.axes and not pad.buttons
    pad.close()


@pytest.mark.parametrize('kwargs', [dict(hz=0),dict(deadzone=1),dict(translation_m_s=float('nan')),
    dict(signs=(1,)*5),dict(signs=(2,)*6)])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):Mapping(**kwargs)


def test_duplicate_and_out_of_order_candidates_are_not_replayed():
    a=Arbiter(Mapping());a.select(True,False,{},1)
    assert a.offer([0]*6,1.1,1.1)
    assert a.select(True,False,{},1.11)[0] == 'policy'
    assert not a.offer([0]*6,1.1,1.12)
    assert not a.offer([0]*6,1.09,1.12)
    assert a.select(True,False,{},1.13)[0] == 'paused_no_policy'
