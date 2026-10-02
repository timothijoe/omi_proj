from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.real.ros_topics import decode_image_message
from omi_hil_rl.real.tactile_live import FrameJoiner, dashboard, validate_field


@pytest.mark.parametrize("bigendian", [False, True])
def test_vector_image_decodes_signed_channels_and_row_padding(bigendian):
    rows = np.array([[1, -2, 3, -4, 99, 99], [5, -6, 7, -8, 99, 99]], dtype=">f4" if bigendian else "<f4")
    msg = SimpleNamespace(height=2, width=2, step=24, encoding="32FC2", is_bigendian=bigendian, data=rows.tobytes())
    decoded = decode_image_message(msg)
    np.testing.assert_array_equal(decoded, [[[1, -2], [3, -4]], [[5, -6], [7, -8]]])
    assert decoded.dtype == np.float32


def test_join_never_mixes_fields_from_different_source_frames():
    join = FrameJoiner()
    assert join.add("deformation", 10, "d10") is None
    assert join.add("shear", 11, "s11") is None
    assert join.add("raw", 10, "r10") is None
    assert join.add("metadata", 10, {}) is None
    result = join.add("shear", 10, "s10")
    assert result["deformation"] == "d10"
    assert result["shear"] == "s10"
    join.add("raw", 2, "loop")
    assert 11 not in join.pending
    for stamp in range(20, 50):
        join.add("raw", stamp, "raw")
    assert len(join.pending) == 8


def test_dashboard_valid_stale_and_missing_do_not_modify_numeric_fields():
    field = np.ones((288, 384, 2), dtype=np.float32)
    sample = dict(raw=np.zeros((270, 360), dtype=np.uint8), deformation=field, shear=field,
                  received=1.0, metadata=dict(source_timestamp_ns=123, baseline_id="abcdef", processing_ms=2))
    fresh = dashboard({"a": sample}, 1.1)
    stale = dashboard({"a": sample}, 2.0)
    assert fresh.shape == (740, 1152, 3)
    assert fresh.dtype == np.uint8
    assert np.any(fresh != stale)
    np.testing.assert_array_equal(field, 1)


@pytest.mark.parametrize("value", [np.zeros((2, 2)), np.zeros((2, 2, 2), dtype=int), np.full((2, 2, 2), np.nan)])
def test_invalid_fields_are_rejected(value):
    with pytest.raises(ValueError):
        validate_field(value)
