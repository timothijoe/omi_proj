import math
import numpy as np
import pytest
from omi_hil_rl.real.sdk_action import output_action
from omi_hil_rl.training.eef_action import from_rotvec

R_BO = np.array([[1,0,0],[0,0,-1],[0,1,0]])


def sdk_matrix(abc_deg):
    a,b,c = np.radians(abc_deg)
    ca,sa,cb,sb,cc,sc = math.cos(a),math.sin(a),math.cos(b),math.sin(b),math.cos(c),math.sin(c)
    rx = np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
    ry = np.array([[cb,0,sb],[0,1,0],[-sb,0,cb]])
    rz = np.array([[cc,-sc,0],[sc,cc,0],[0,0,1]])
    return rz@ry@rx


def quaternion_matrix(r):
    x,y,z,w = from_rotvec(r)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


@pytest.mark.parametrize('axis',range(6))
@pytest.mark.parametrize('sign',[-1,1])
def test_single_axis_mapping(axis,sign):
    d=np.zeros(6);d[axis]=sign*(.001 if axis<3 else math.pi/180)
    result=output_action(d,'sdk-x-forward-z-left')
    target=np.r_[R_BO@d[:3]*1000, np.degrees(R_BO@d[3:])]
    np.testing.assert_allclose(result,target,atol=1e-12)


@pytest.mark.parametrize('r',[[0,0,0],[.2,-.3,.1],[0,0,math.pi/2],[0,0,-math.pi/2],[1.2,.5,-.8],[1e-10,-2e-10,3e-10]])
@pytest.mark.parametrize('mode',['sdk-base-aligned','sdk-x-forward-z-left'])
def test_sdk_rotation_matches_conjugated_policy_rotation(r,mode):
    d=np.r_[[.001,.002,.003],r]
    out=output_action(d,mode)
    frame=R_BO if mode=='sdk-x-forward-z-left' else np.eye(3)
    np.testing.assert_allclose(out[:3],frame@d[:3]*1000,atol=1e-12)
    np.testing.assert_allclose(sdk_matrix(out[3:]),frame@quaternion_matrix(r)@frame.T,atol=1e-10)


def test_combined_angles_require_more_than_permutation():
    r=np.array([.2,.3,.4])
    out=output_action(np.r_[np.zeros(3),r],'sdk-x-forward-z-left')
    assert not np.allclose(out[3:],np.degrees(R_BO@r))


@pytest.mark.parametrize('d,mode',[([0]*5,'legacy'),([float('nan')]*6,'sdk-base-aligned'),([0]*6,'unknown')])
def test_invalid_input(d,mode):
    with pytest.raises(ValueError):output_action(d,mode)
