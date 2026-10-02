import numpy as np
import pytest

from omi_hil_rl.real.tactile_vectors import render_vector_field


def test_zero_field_draws_nothing():
    image, stats = render_vector_field(np.zeros((32, 32, 2), dtype=np.float32), step=16)

    assert not np.any(image)
    assert stats.sampled_vectors == 4
    assert stats.drawn_vectors == 0
    assert stats.clipped_vectors == 0


def test_positive_x_and_negative_y_follow_image_coordinates():
    plus_x = np.zeros((32, 32, 2), dtype=np.float32)
    plus_x[..., 0] = 1.0
    image_x, _ = render_vector_field(plus_x, step=16, scale_px_per_unit=5, deadband=0)
    assert np.any(image_x[8, 9:14, 1] == 255)

    minus_y = np.zeros((32, 32, 2), dtype=np.float32)
    minus_y[..., 1] = -1.0
    image_y, _ = render_vector_field(minus_y, step=16, scale_px_per_unit=5, deadband=0)
    assert np.any(image_y[3:8, 8, 1] == 255)


def test_clipped_arrows_are_counted_and_colored_red():
    field = np.zeros((32, 32, 2), dtype=np.float32)
    field[..., 0] = 100.0

    image, stats = render_vector_field(
        field,
        step=16,
        scale_px_per_unit=10,
        deadband=0,
        max_arrow_px=4,
    )

    assert stats.clipped_vectors == 4
    assert np.any(image[..., 0] == 255)


def test_renderer_rejects_wrong_dtype_shape_and_nonfinite_values():
    with pytest.raises(ValueError, match="floating dtype"):
        render_vector_field(np.zeros((4, 4, 2), dtype=np.int16))
    with pytest.raises(ValueError, match="HxWx2"):
        render_vector_field(np.zeros((4, 4), dtype=np.float32))
    invalid = np.zeros((4, 4, 2), dtype=np.float32)
    invalid[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or Inf"):
        render_vector_field(invalid)
