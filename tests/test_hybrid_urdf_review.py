import xml.etree.ElementTree as ET

from omi_hil_rl.real.hybrid_urdf_review import combine
from omi_hil_rl.real.robot_replay_3d import PREFIX


def model():
    root = ET.Element('robot')
    for name in ['robot_base'] + [f'{s}_link{i}' for s in ('left', 'right') for i in range(1, 8)]:
        link = ET.SubElement(root, 'link', name=PREFIX+name)
        v = ET.SubElement(link, 'visual')
        ET.SubElement(v, 'origin', xyz='0 0 0', rpy='0 0 0')
        ET.SubElement(ET.SubElement(v, 'geometry'), 'mesh', filename='old.stl')
        if name != 'robot_base':
            j = ET.SubElement(root, 'joint', name=name, type='revolute')
            ET.SubElement(j, 'origin', xyz='0 0 .1745', rpy='1.2 0 0')
            ET.SubElement(j, 'axis', xyz='0 -1 0')
    return root


def test_hybrid_keeps_entire_joint_chain_and_fallbacks():
    old, new = model(), model()
    for mesh in new.findall('.//mesh'):
        mesh.set('filename', 'new.stl')
    fits = {PREFIX+f'{side}_link{i}': dict(accepted=i!=7, xyz=[0,0,.1], rpy=[0,0,1])
            for side in ('left','right') for i in range(1,8)}
    before = ET.tostring(old)
    result = combine(old, new, fits)
    assert before == ET.tostring(old)
    assert [ET.tostring(j) for j in result.findall('joint')] == [ET.tostring(j) for j in old.findall('joint')]
    assert result.find(f"link[@name='{PREFIX}left_link1']/visual/geometry/mesh").get('filename') == 'new.stl'
    assert result.find(f"link[@name='{PREFIX}left_link7']/visual/geometry/mesh").get('filename') == 'old.stl'
    assert result.find(f"link[@name='{PREFIX}robot_base']/visual/origin").get('xyz') == '0 0 -0.90205'
