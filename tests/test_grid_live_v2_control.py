from types import SimpleNamespace as S
import math

import numpy as np
import pytest

from omi_hil_rl.real.grid_live_v2_control import Signals, command_geometry, control_image, pose_values


def command(values, ident='hil:sample'):
    return S(data=values, layout=S(dim=[S(label=ident)]))


def pose():
    return S(header=S(frame_id='base_link', stamp=S(sec=1, nanosec=20)),
             pose=S(position=S(x=.628, y=-.034, z=.8),
                    orientation=S(x=0., y=0., z=math.sin(math.pi/4), w=math.cos(math.pi/4))))


def test_pose_mm_quaternion_to_zyx_display_and_bad_quaternion():
    p = pose();v = pose_values(p)
    np.testing.assert_allclose(v['xyz_mm'], [628, -34, 800])
    np.testing.assert_allclose(v['rpy_deg'], [0, 0, 90], atol=1e-10)
    assert v['frame'] == 'base_link'
    p.pose.orientation.w = 0
    with pytest.raises(ValueError):
        pose_values(p)


def test_lanes_stay_independent_and_do_not_infer_control_ownership():
    s = Signals();s.route('human', '/custom/manual');s.route('policy', '/custom/policy')
    s.ingest('human', command([1, 0, 0, 0, 0, 0]), 10**9)
    s.ingest('policy', command([0]*6), 10**9+1)  # delayed stop from the other route
    v = s.snapshot(10**9+10)
    assert v['signals']['human']['value']['components'][0] == 1
    assert v['signals']['policy']['value']['components'] == [0]*6
    assert 'active_source' not in v
    s.route('human', '/different/manual')
    assert s.snapshot(10**9+20)['signals']['human']['state'] == 'WAITING'


def test_stale_command_retained_but_marked_and_invalid_not_zero():
    s = Signals();s.ingest('human', command([.2]*6), 10**9)
    old = s.snapshot(2*10**9)['signals']['human']
    assert old['state'] == 'STALE' and old['value']['components'] == [.2]*6
    s.ingest('human', command([float('nan')]*6), 2*10**9)
    bad = s.snapshot(2*10**9)['signals']['human']
    assert bad['state'] == 'BAD_DATA' and bad['value'] is None


def test_bar_clipping_preserves_wire_numbers_and_negative_sign():
    values = [3, -.75, 0, -.5, .2, 2]
    fractions, overflow = command_geometry(values, 1.5, 1.)
    assert fractions == [1, -.5, 0, -.5, .2, 1]
    assert overflow == [True, False, False, False, False, True]
    assert values[0] == 3
    s = Signals();s.ingest('policy', command(values), 10**9)
    assert control_image(s.snapshot(10**9)).size == (1800, 620)


def test_missing_pose_and_receipt_and_invalid_receipt_render():
    s = Signals()
    assert control_image(s.snapshot(10**9)).size == (1800, 620)
    s.ingest('receipt', S(data='{"accepted":true,"status":"queue_accepted","action_source":"human","execution_confirmed":false}'), 10**9)
    assert s.snapshot(10**9)['signals']['receipt']['value']['execution_confirmed'] is False
    s.ingest('receipt', S(data='{"accepted":true,"status":NaN}'), 10**9+1)
    assert s.snapshot(10**9+1)['signals']['receipt']['state'] == 'BAD_DATA'
