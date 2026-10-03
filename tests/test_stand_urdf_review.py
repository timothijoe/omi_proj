import xml.etree.ElementTree as ET

import pytest

from omi_hil_rl.real.stand_urdf_review import convert, legacy_axis_mapping, LEGACY_AXIS_SIGNS


def fixture_model():
    root = ET.Element("robot", name="test")
    ET.SubElement(root, "link", name="ZJ_Robot_link")
    for side in "LR":
        for i in range(1, 8):
            name = f"Arm_{side}{i}_Link"
            ET.SubElement(root, "link", name=name)
            j = ET.SubElement(root, "joint", name=f"Arm_{side}{i}_Joint", type="revolute")
            ET.SubElement(j, "parent", link="ZJ_Robot_link" if i == 1 else f"Arm_{side}{i-1}_Link")
            ET.SubElement(j, "child", link=name)
            ET.SubElement(j, "origin", xyz="0 .2005 1.121" if i == 1 else "0 0 0", rpy="1.57 0 0")
            ET.SubElement(j, "axis", xyz="0 0 -1")
            ET.SubElement(j, "limit", lower="-1", upper="1", effort="18", velocity="3")
    return root


def test_convert_preserves_kinematics_and_explicit_root():
    root = fixture_model()
    root.find("joint/child").tail = "+123456"
    text, limits, cleanups = convert(ET.tostring(root), {})
    out = ET.fromstring(text)
    assert cleanups == ["+123456"]
    assert len(limits) == 14
    for old, new in zip(root.findall("joint"), out.findall("joint")[:14]):
        for tag in ("origin", "axis", "limit"):
            assert old.find(tag).attrib == new.find(tag).attrib
    fixed = out.find("joint[@name='stand_review_root']")
    assert fixed.find("origin").get("xyz") == "0 0 0"
    assert fixed.find("child").get("link") == "omi_replay_robot_base"
    assert out.find("joint[@name='left_joint7']/child").get("link") == "omi_replay_left_link7"


def test_reject_unexpected_chain():
    root = fixture_model()
    root.find("joint/parent").set("link", "Arm_L7_Link")
    with pytest.raises(ValueError, match="chain"):
        convert(ET.tostring(root), {})


def test_mesh_must_exist_and_is_resolved(tmp_path):
    root = fixture_model()
    mesh = ET.SubElement(ET.SubElement(ET.SubElement(root.find("link"), "visual"), "geometry"),
                         "mesh", filename="package://model/meshes/base.STL")
    with pytest.raises(ValueError, match="Missing archive mesh"):
        convert(ET.tostring(root), {})
    text, _, _ = convert(ET.tostring(root), {"model/meshes/base.STL": tmp_path / "base.STL"})
    assert ET.fromstring(text).find(".//mesh").get("filename") == (tmp_path / "base.STL").as_uri()


def test_wrong_link_set_rejected():
    root = fixture_model()
    ET.SubElement(root, "link", name="guessed_tcp")
    with pytest.raises(ValueError, match="link set"):
        convert(ET.tostring(root), {})


def test_corrected_axes_preserve_origins_and_transform_limits():
    text, _, _ = convert(ET.tostring(fixture_model()), {})
    original = ET.fromstring(text)
    corrected = ET.fromstring(legacy_axis_mapping(text))
    for side, signs in LEGACY_AXIS_SIGNS.items():
        for i, sign in enumerate(signs, 1):
            path = f"joint[@name='{side}_joint{i}']"
            a, b = original.find(path), corrected.find(path)
            for tag in ('origin', 'parent', 'child'):
                assert a.find(tag).attrib == b.find(tag).attrib
            assert [float(v) for v in b.find('axis').get('xyz').split()] == [sign*float(v) for v in a.find('axis').get('xyz').split()]
    # Direction conversion must be reversible even for asymmetric limits.
    original.find("joint[@name='left_joint4']/limit").set('lower', '-2.5')
    corrected = ET.fromstring(legacy_axis_mapping(ET.tostring(original)))
    assert corrected.find("joint[@name='left_joint4']/limit").get('upper') == '2.5'
    restored = ET.fromstring(legacy_axis_mapping(ET.tostring(corrected)))
    assert float(restored.find("joint[@name='left_joint4']/limit").get('lower')) == -2.5
