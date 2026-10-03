import numpy as np
import pytest
from omi_hil_rl.real import grid_recorded_review as grid


def test_all_grid_vectors_sampled_without_rescaling():
    field=np.zeros((16,24,2),np.float32)
    field[...,0]=.5
    before=field.copy()
    image,stats=grid.vector_preview(field)
    assert image.shape==(256,384,3)
    assert stats.sampled_vectors==384 and stats.drawn_vectors==384 and stats.clipped_vectors==0
    np.testing.assert_array_equal(field,before)


def test_shapes_and_no_control_topics():
    with pytest.raises(ValueError): grid.vector_preview(np.zeros((288,384,2)))
    assert not any('/control/' in topic for topic in grid.TOPICS)
    assert '/omi/wrist/color/image_roi' in grid.TOPICS
    assert not any(topic.endswith('/raw') for topic in grid.TOPICS)


def test_roi_no_second_crop_and_depth_display():
    roi=np.full((128,128,3),[250,10,30],np.uint8)
    item=lambda value: dict(value=value,stamp=1_000_000_000,frame='test')
    out=np.asarray(grid.render({'wrist_roi':item(roi),'a_depth':item(np.zeros((16,24),np.float32))},1_000_000_000,0))
    np.testing.assert_array_equal(out[110,810],[250,10,30])
    np.testing.assert_array_equal(out[760,10],[0,0,255])
    assert grid.render({},1_000_000_000,0).size==(1536,1170)


@pytest.mark.parametrize('value',['0','-1','nan','inf'])
def test_rate_validation(value):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError): grid.positive(value)


def test_decoder_rejects_full_field(monkeypatch):
    monkeypatch.setattr(grid.base,'decode',lambda key,msg:dict(value=np.zeros((288,384,2))))
    with pytest.raises(ValueError,match='expected'): grid.decode('a_deformation',None)


@pytest.mark.parametrize('zipped',[False,True])
def test_receipt_order_opt_in_keeps_headers_and_strict_default(tmp_path,monkeypatch,zipped):
    import json
    import sys
    import zipfile
    from types import SimpleNamespace as Obj
    from PIL import Image
    yaml=pytest.importorskip('yaml')
    topic='/omi/tactile_grid24x16/a/depth'
    class Reader:
        def __init__(self): self.pending=True
        def open(self,*args): pass
        def get_all_topics_and_types(self): return [Obj(name=topic,type='test')]
        def set_filter(self,*args): pass
        def has_next(self): return self.pending
        def read_next(self):
            self.pending=False
            return topic,b'',1_000_000_000
    monkeypatch.setitem(sys.modules,'rosbag2_py',Obj(SequentialReader=Reader,StorageOptions=lambda **k:k,
                        ConverterOptions=lambda *a:a,StorageFilter=lambda **k:k))
    monkeypatch.setitem(sys.modules,'rclpy.serialization',Obj(deserialize_message=lambda *a:None))
    monkeypatch.setitem(sys.modules,'rosidl_runtime_py.utilities',Obj(get_message=lambda *a:None))
    info=dict(storage_identifier='mcap',relative_file_paths=['part.mcap'],duration={'nanoseconds':100_000_000},
              starting_time={'nanoseconds_since_epoch':1_000_000_000},topics_with_message_count=[])
    folder=tmp_path/'bag';folder.mkdir()
    (folder/'metadata.yaml').write_text(yaml.safe_dump({'rosbag2_bagfile_information':info}))
    (folder/'part.mcap').write_bytes(b'fake')
    source=folder
    if zipped:
        source=tmp_path/'bag.zip'
        with zipfile.ZipFile(source,'w') as z:
            z.write(folder/'metadata.yaml','nested/metadata.yaml')
            z.write(folder/'part.mcap','nested/part.mcap')
    kwargs=dict(topics={topic:'a_depth'},decoder=lambda *a:dict(stamp=1_022_000_000,frame='tactile_a',value=np.zeros((16,24))),
                renderer=lambda *a:Image.new('RGB',(2,2)),cache_version='test')
    with pytest.raises(ValueError,match='later than bag receipt'):
        grid.base.prepare(source,tmp_path/'cache',**kwargs)
    dest=grid.base.prepare(source,tmp_path/'cache',allow_future_headers=True,**kwargs)
    manifest=json.loads((dest/'manifest.json').read_text())
    assert manifest['future_headers']['a_depth']==dict(count=1,max_ahead_ns=22_000_000)
    assert manifest['frames'][-1]['source_stamps']['a_depth']==1_022_000_000
    assert grid.base.prepare(source,tmp_path/'cache',allow_future_headers=True,**kwargs)==dest
