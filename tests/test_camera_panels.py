import numpy as np
from PIL import Image

from omi_hil_rl.real.camera_panels import camera_panel, prepare_camera


def test_camera_crop_matches_existing_viewer_and_clip_stays_literal_128_pixels():
    rng = np.random.default_rng(7)
    source = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
    sample = prepare_camera(source, "head", 123, 1.0)
    assert sample["roi"] == (228, 108, 192)
    expected = Image.fromarray(source[108:300, 228:420]).resize((128, 128), Image.Resampling.LANCZOS)
    np.testing.assert_array_equal(sample["clip"], expected)
    panel = camera_panel({"head": sample}, 1.1)
    assert panel.shape == (740, 640, 3)
    np.testing.assert_array_equal(panel[187:315, 496:624], expected)
    assert np.any(panel != camera_panel({"head": sample}, 2.0))


def test_wrist_roi_center_and_missing_camera_panel():
    sample = prepare_camera(np.zeros((1080, 1920, 3), dtype=np.uint8), "wrist", 123, 1.0)
    assert sample["roi"] == (766, 566, 389)
    assert sample["original"].size == (480, 270)
    assert camera_panel({}, 1.0).shape == (740, 640, 3)
