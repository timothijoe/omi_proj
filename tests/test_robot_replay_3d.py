import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from omi_hil_rl.real.robot_replay_3d import JOINTS, PREFIX, ReplayPose, build_urdf, origin
from omi_hil_rl.real.robot_state_panel import Timeline

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "local/assets/robot_assets/mujoco/right_chopping_scene.xml"


def test_quaternion_origin_and_unsupported_rotation():
    result = origin(ET.fromstring('<body pos="1 2 3" quat="0.7071067811865476 0 0 0.7071067811865476"/>'))
    np.testing.assert_allclose(np.fromstring(result['rpy'], sep=' '), [0, 0, math.pi/2], atol=1e-12)
    with pytest.raises(ValueError):
        origin(ET.fromstring('<body euler="0 0 0"/>'))


def test_pose_selection_loop_pause_and_limits():
    records = {"feedback": [dict(stamp=s, clock='header', values={'positions': [q]*14})
                            for s, q in [(10**9, .1), (2*10**9, .2)]]}
    pose = ReplayPose(Timeline(records), {n: [-.15, .15] for n in JOINTS})
    assert pose.sample(0)[0] is None
    pose.update(2*10**9, 1)
    assert pose.sample(1)[1]['state'] == 'MODEL_LIMIT_WARNING'
    pose.update(2*10**9, 2)  # repeating the header is NOT fresh
    assert pose.sample(2)[1]['state'] == 'STALE_OR_PAUSED'
    pose.update(10**9, 3)  # historical loop, but current-time TF will be used
    assert pose.sample(3)[0] == [.1]*14
    pose.update(10, 4)
    assert pose.sample(4)[0] is None  # no future sample


def rotation(axis, angle):
    x, y, z = axis / np.linalg.norm(axis)
    skew = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3) + math.sin(angle)*skew + (1-math.cos(angle))*(skew @ skew)


@pytest.mark.skipif(not SCENE.is_file(), reason='local model assets not restored')
def test_arm_urdf_matches_mujoco_forward_kinematics():
    mujoco = pytest.importorskip('mujoco')
    urdf, limits, meshes = build_urdf(SCENE)
    tree = ET.fromstring(urdf)
    assert set(limits) == set(JOINTS)
    assert len(tree.findall('link')) == 16
    assert all(p.is_file() for p in meshes)
    assert 'knife' not in urdf and 'wuji' not in urdf
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    q = {name: float(value) for name, value in zip(JOINTS, np.linspace(-.3, .3, 14))}
    for name, value in q.items():
        data.qpos[model.jnt_qposadr[model.joint(name).id]] = value
    mujoco.mj_forward(model, data)
    transforms = {PREFIX+'world': np.eye(4)}
    for joint in tree.findall('joint'):
        frame = np.eye(4)
        frame[:3,3] = np.fromstring(joint.find('origin').get('xyz'), sep=' ')
        r,p,y = np.fromstring(joint.find('origin').get('rpy'), sep=' ')
        frame[:3,:3] = rotation(np.array([0,0,1]),y) @ rotation(np.array([0,1,0]),p) @ rotation(np.array([1,0,0]),r)
        if joint.get('type') == 'revolute':
            frame[:3,:3] = frame[:3,:3] @ rotation(np.fromstring(joint.find('axis').get('xyz'), sep=' '),q[joint.get('name')])
        parent = joint.find('parent').get('link')
        child = joint.find('child').get('link')
        transforms[child] = transforms[parent] @ frame
        body_id = model.body(child.removeprefix(PREFIX)).id
        np.testing.assert_allclose(transforms[child][:3,3], data.xpos[body_id], atol=1e-8)
        np.testing.assert_allclose(transforms[child][:3,:3], data.xmat[body_id].reshape(3,3), atol=1e-8)


def test_3d_launcher_is_separate_and_does_not_replay_control():
    text = (ROOT/'scripts/view_observation_robot_3d_bag.sh').read_text()
    assert 'view_observation_robot_bag.sh' in text
    assert '/tj/control' not in text
    assert '/omi/replay_3d/tf' in text
