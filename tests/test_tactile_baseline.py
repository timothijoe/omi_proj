import numpy as np
import pytest

from omi_hil_rl.real.tactile_baseline import (
    raw_stability,
    temporal_median_uint8,
    zero_load_checks,
)


def test_temporal_median_rejects_noise_and_preserves_uint8_shape():
    frames = [
        np.asarray([[10, 20], [30, 40]], dtype=np.uint8),
        np.asarray([[10, 200], [30, 40]], dtype=np.uint8),
        np.asarray([[11, 20], [30, 39]], dtype=np.uint8),
    ]

    result = temporal_median_uint8(frames)

    assert result.dtype == np.uint8
    np.testing.assert_array_equal(result, [[10, 20], [30, 40]])


def test_temporal_median_rejects_incompatible_frames():
    with pytest.raises(ValueError, match="same HxW"):
        temporal_median_uint8(
            [np.zeros((2, 2), dtype=np.uint8), np.zeros((3, 2), dtype=np.uint8)]
        )


def test_raw_stability_reports_temporal_brightness_and_pixel_motion():
    frames = [
        np.zeros((2, 2), dtype=np.uint8),
        np.ones((2, 2), dtype=np.uint8),
        np.full((2, 2), 2, dtype=np.uint8),
    ]

    result = raw_stability(frames)

    assert result["pixel_mean"] == pytest.approx(1.0)
    assert result["pixel_mean_std_over_time"] == pytest.approx(np.std([0, 1, 2]))
    assert result["successive_frame_mae"] == pytest.approx(1.0)


def test_zero_load_checks_require_open_gripper_low_force_and_low_depth():
    passed = zero_load_checks(
        gripper_positions=[1.0, 1.0],
        wrench_a=[np.asarray([0.1, 0.0, 0.2, 0, 0, 0])],
        wrench_b=[np.asarray([0.0, 0.1, 0.2, 0, 0, 0])],
        depth_means_a=[0.006, 0.007],
        depth_means_b=[0.005, 0.006],
    )
    failed = zero_load_checks(
        gripper_positions=[0.8],
        wrench_a=[np.asarray([0.0, 0.0, 2.0, 0, 0, 0])],
        wrench_b=[np.asarray([0.0, 0.0, 2.0, 0, 0, 0])],
        depth_means_a=[0.08],
        depth_means_b=[0.08],
    )

    assert passed["all_passed"] is True
    assert all(passed["checks"].values())
    assert failed["all_passed"] is False
    assert not any(failed["checks"].values())
