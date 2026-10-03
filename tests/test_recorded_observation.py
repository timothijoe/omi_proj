from pathlib import Path
from types import SimpleNamespace as Obj

import numpy as np
import pytest

from omi_hil_rl.real.recorded_observation import (
    TOPICS, WIDTH, HEIGHT, age_label, camera_preview, decode, render, tactile_preview_display,
)


def header():
    return Obj(stamp=Obj(sec=1, nanosec=0), frame_id="base_link")


def test_camera_uses_existing_observation_roi_and_true_128_pixels():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    image[108:300, 228:420] = 97
    result, roi = camera_preview(image)
    assert roi == (228, 108, 192)
    assert result.shape == (128, 128, 3)
    assert np.all(result == 97)


def test_decode_robot_shapes_and_pose_validation():
    assert decode("joints", Obj(header=header(), arm_positions=[.1]*14))["value"].shape == (14,)
    with pytest.raises(ValueError):
        decode("joints", Obj(header=header(), arm_positions=[.1]*7))
    msg = Obj(header=header(), pose=Obj(position=Obj(x=.5, y=.1, z=.8), orientation=Obj(x=0., y=0., z=0., w=1.)))
    assert decode("eef", msg)["value"].tolist() == [.5, .1, .8, 0., 0., 0., 1.]
    msg.pose.orientation.w = 0.
    with pytest.raises(ValueError):
        decode("eef", msg)


def test_stale_and_waiting_and_dashboard_layout():
    assert age_label(None, 10**9) == "WAITING"
    assert age_label(dict(stamp=10**9), 2*10**9).startswith("STALE")
    assert age_label(dict(stamp=2*10**9), 10**9).startswith("FUTURE")
    assert render({}, 10**9, 0).size == (WIDTH, HEIGHT)
    sample = dict(stamp=10**9, frame="tactile_a", value=np.ones((288, 384, 2), dtype=np.float32)*.1)
    assert render({"a_deformation": sample}, 10**9, 0).size == (WIDTH, HEIGHT)


def test_no_commands_in_source_allowlist_and_separate_launcher():
    assert not any("/control/" in key for key in TOPICS)
    root = Path(__file__).resolve().parents[1]
    launcher = (root/"scripts/view_recorded_observation_3d.sh").read_text()
    assert "ros2 bag play" not in launcher
    assert "view_observation_bag.sh" not in launcher
    assert "ROS_LOCALHOST_ONLY=1" in launcher
    module = (root/"src/omi_hil_rl/real/recorded_observation.py").read_text()
    assert "extractall" not in module
    assert "sensor.get" not in module


def test_tactile_preview_top_right_and_original_bottom_right():
    rng = np.random.default_rng(42)
    raw = rng.integers(0, 256, (270, 360), dtype=np.uint8)
    original = raw.copy()
    preview = tactile_preview_display(raw)
    assert preview.shape == raw.shape and preview.dtype == np.uint8
    assert not np.array_equal(preview, raw)
    np.testing.assert_array_equal(raw, original)
    latest = {s+"_raw": dict(stamp=10**9, frame="tactile_"+s, value=raw) for s in "ab"}
    canvas = np.asarray(render(latest, 10**9, 0))
    for col in (2, 3):
        x = col*384+12
        for row, expected in ((0, preview), (2, raw)):
            y = 58+row*324+42
            np.testing.assert_array_equal(canvas[y:y+270, x:x+360], np.repeat(expected[...,None], 3, axis=2))
