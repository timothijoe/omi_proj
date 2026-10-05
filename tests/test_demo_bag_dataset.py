"""Bag snapshots round-trip without replay, and per-frame dataset visualization."""
import copy
from functools import partial
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
import threading
from urllib.request import urlopen

import numpy as np
from PIL import Image
import pytest

from omi_hil_rl.hil.config import HILConfig
from omi_hil_rl.hil.demo import collect, read_demo_step
from omi_hil_rl.hil.demo_bag import SAMPLE_TOPIC, encode_sample, convert_records, bag_records
from omi_hil_rl.training.demo_view import DatasetView, Handler


@pytest.fixture
def capture(tmp_path):
    root=tmp_path/'source'
    manifests=collect(root,HILConfig(),episodes=2,fake_steps=2)
    records=[]
    for manifest in manifests:
        for i in range(manifest['count']):
            records.append((SAMPLE_TOPIC,encode_sample(manifest['episode'],i,root/'episodes'/manifest['episode']/f'{i:06d}.npz'),10+i))
        records.append(('/omi/demo/event',dict(kind='episode_end',**manifest),20))
    return root,manifests,records


def test_exact_roundtrip_and_view_http(capture,tmp_path):
    source,manifests,records=capture
    output=tmp_path/'converted'
    report=convert_records(records,output,source='example/raw')
    assert report['samples']==4 and report['episodes']==2
    for manifest in manifests:
        for i in range(2):
            a=read_demo_step(source/'episodes'/manifest['episode'],i)
            b=read_demo_step(output/'episodes'/manifest['episode'],i)
            for group in range(2):
                for key in a[group]:np.testing.assert_array_equal(a[group][key],b[group][key])
            np.testing.assert_array_equal(a[2],b[2]);assert a[3]==b[3]
    view=DatasetView(output)
    assert Image.open(BytesIO(view.frame(0,0))).size==(1536,1060)
    assert view.frame(0,0)!=view.frame(0,0,after=True)
    with pytest.raises(ValueError):view.frame(0,999)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,view=view))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        assert len(json.load(urlopen(base+'/catalog'))['episodes'])==2
        assert urlopen(base+'/frame?episode=0&step=1&slot=5').headers['Content-Type']=='image/png'
        assert '观测'.encode() in urlopen(base).read()
    finally:server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('problem',['missing','hash','path','chronology'])
def test_incomplete_or_corrupt_bag_is_not_published(capture,tmp_path,problem):
    _,_,records=capture
    records=copy.deepcopy(records)
    if problem=='missing':records.pop(0)
    elif problem=='hash':records[0][1]['sha256']='wrong'
    elif problem=='path':records[0][1]['episode']='../../escape'
    else:
        # Repeating an earlier frame under another step cannot pass metadata/chronology.
        records[1][1]['npz_base64']=records[0][1]['npz_base64']
        records[1][1]['sha256']=records[0][1]['sha256']
    with pytest.raises(ValueError):convert_records(records,tmp_path/'out',source='test')
    assert not list((tmp_path/'out').glob('episodes/*/demo.json'))
    with pytest.raises(ValueError,match='incomplete'):DatasetView(tmp_path/'out')


def test_actual_rosbag_offline_conversion(capture,tmp_path):
    try:
        import rosbag2_py as rosbag
    except ImportError:
        pytest.skip('ROS environment not sourced')
    from rclpy.serialization import serialize_message
    from std_msgs.msg import String
    _,_,records=capture
    bag=tmp_path/'bag'
    writer=rosbag.SequentialWriter()
    writer.open(rosbag.StorageOptions(uri=str(bag),storage_id='sqlite3'),rosbag.ConverterOptions('',''))
    for i,topic in enumerate((SAMPLE_TOPIC,'/omi/demo/event')):
        writer.create_topic(rosbag.TopicMetadata(id=i,name=topic,type='std_msgs/msg/String',serialization_format='cdr'))
    for i,(topic,row,_) in enumerate(records):
        writer.write(topic,serialize_message(String(data=json.dumps(row))),1_000_000_000+i)
    del writer
    report=convert_records(bag_records(bag),tmp_path/'from_bag',source=bag)
    assert report['samples']==4


def test_view_preserves_camera_and_tactile_channel_order(capture):
    from omi_hil_rl.training.demo_view import render
    root,manifests,_=capture
    m=manifests[0]
    obs,_,action,meta=read_demo_step(root/'episodes'/m['episode'],0)
    obs['rgb'][:]=0;obs['rgb'][:,0]=255
    obs['wrist_rgb'][:]=0;obs['wrist_rgb'][:,1]=255
    obs['camera_mask'][:]=1
    obs['tactile'][:,4]=0
    obs['tactile'][:,9]=.3
    image=np.asarray(Image.open(BytesIO(render(obs,action,meta,m,0,9,False))))
    assert tuple(image[200,100])==(255,0,0)
    assert tuple(image[200,400])==(0,255,0)
    assert tuple(image[700,850])==(0,0,255)
    assert tuple(image[700,1250])==(255,255,0)
