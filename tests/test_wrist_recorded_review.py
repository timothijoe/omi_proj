import numpy as np
from omi_hil_rl.real import recorded_observation as base
from omi_hil_rl.real.wrist_recorded_review import wrist_preview, render, VERSION


def test_legacy_crop_has_explicit_bounds_and_128_shape():
    im=np.zeros((1080,1920,3),dtype=np.uint8)
    im[0,420]=[255,0,0]
    small,box=wrist_preview(im)
    assert box==(766,566,389)
    assert small.shape==(128,128,3)
    assert im[0,420].tolist()==[255,0,0]


def test_preview_exactly_matches_legacy_viewer():
    from omi_hil_rl.real.camera_panels import prepare_camera
    for h,w in [(1080,1920),(270,360),(192,108)]:
        rgb=np.random.default_rng(7).integers(0,256,(h,w,3),dtype=np.uint8)
        expected=prepare_camera(rgb,'wrist',1,0)
        small,box=wrist_preview(rgb)
        assert box==expected['roi']
        np.testing.assert_array_equal(small,np.asarray(expected['clip']))


def test_wrist_tiles_do_not_change_other_observation_tiles():
    item=dict(stamp=1000000000,frame='gripper_camera',value=np.full((108,192,3),[255,0,0],dtype=np.uint8))
    state={'wrist':item}
    before=np.asarray(base.render(state,1000000000,0))
    after=np.asarray(render(state,1000000000,0))
    assert np.array_equal(before[58:382,:768],after[58:382,:768])
    assert np.array_equal(before[382:1130],after[382:1130])
    assert np.any(after[100:378,768:]!=before[100:378,768:])
    assert VERSION!=base.VERSION


def test_missing_wrist_renders_without_substituting_other_images():
    output=render({},1000000000,0)
    assert output.size==(base.WIDTH,base.HEIGHT)
    assert np.array_equal(np.asarray(output)[200,1100],[18,22,28])
