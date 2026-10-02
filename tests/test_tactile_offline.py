import numpy as np
import pytest

from omi_hil_rl.real.tactile_offline import depth_comparison, numeric_stats


def test_numeric_stats_records_shape_dtype_and_range():
    result = numeric_stats(np.asarray([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32))
    assert result["shape"] == [2, 2]
    assert result["dtype"] == "float32"
    assert result["min"] == 0.0
    assert result["max"] == 3.0


def test_depth_comparison_reports_exact_match_and_scale():
    source = np.asarray([[1.0, 2.0]], dtype=np.float32)
    exact = depth_comparison(source, source)
    scaled = depth_comparison(source, source * 0.5)
    assert exact["mae"] == 0.0
    assert exact["pearson"] == pytest.approx(1.0)
    assert scaled["least_squares_scale_reconstructed_to_recorded"] == pytest.approx(0.5)
