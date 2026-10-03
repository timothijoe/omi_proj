import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ros2/omi_sensors'))
from omi_sensors.wrist_image import prepare_image, TOPICS
from omi_hil_rl.real.observation import ObservationConfig, _crop_square_resize_nearest


@pytest.mark.parametrize('shape', [(1080,1920,3),(480,640,3),(640,480,3),(1,1,3)])
def test_roi_matches_policy(shape):
    image = np.random.default_rng(7).integers(0,256,shape,dtype=np.uint8)
    actual, meta = prepare_image(image,'roi')
    expected, bounds = _crop_square_resize_nearest(image,ObservationConfig().wrist_rgb_roi,(128,128))
    np.testing.assert_array_equal(actual,expected)
    assert meta['roi_xywh'] == [*bounds[:2],bounds[2],bounds[2]]
    assert meta['output_size_wh']==[128,128]
    if shape[:2]==(1080,1920): assert meta['roi_xywh']==[766,566,389,389]


def test_full_unchanged_and_topics_separate():
    image=np.zeros((480,640,3),np.uint8)
    actual,meta=prepare_image(image,'full')
    assert actual is image and meta['roi_xywh'] is None
    assert TOPICS['full'] != TOPICS['roi']
    with pytest.raises(ValueError): prepare_image(image,'wrong')
