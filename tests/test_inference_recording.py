import json
import threading
import numpy as np
from omi_hil_rl.training.inference_recording import InferenceRecorder


def sample():
    return ({'state':np.ones((10,14),np.float32),'wrench':np.ones((10,2,6),np.float32)},np.ones(10,np.uint8))


def test_flush_copies_exact_input_and_action(tmp_path):
    r=InferenceRecorder(tmp_path/'record')
    window=sample();action=np.arange(6,dtype=np.float32)
    name=r.submit(window,action,dict(reference_ns=100,epoch=0,candidate_published=False))
    window[0]['state'][:]=42;action[:]=99
    report=r.close()
    assert report['saved']==1 and report['complete']
    with np.load(tmp_path/'record'/name,allow_pickle=False) as a:
        assert (a['state']==1).all()
        np.testing.assert_array_equal(a['action'],np.arange(6))
        assert json.loads(str(a['metadata']))['reference_ns']==100
    assert json.loads((tmp_path/'record/summary.json').read_text())['flushed']


def test_capacity_and_write_error_are_reported(tmp_path):
    for key in ('capacity','failure'):
        r=InferenceRecorder(tmp_path/key,max_bytes=1 if key=='capacity' else 100000)
        if key=='failure':
            def fail(*args):raise OSError('disk full')
            r._write=fail
        r.submit(sample(),np.zeros(6),dict(reference_ns=1))
        report=r.close()
        assert report['saved']==0 and report['dropped']==1 and report['errors']
        assert not list((tmp_path/key).glob('*.npz'))


def test_queue_full_does_not_block_and_close_drains(tmp_path):
    r=InferenceRecorder(tmp_path/'record',queue_size=1)
    entered=threading.Event();release=threading.Event();original=r._write
    def slow(*args):
        entered.set();release.wait(5);original(*args)
    r._write=slow
    r.submit(sample(),np.zeros(6),dict(reference_ns=1));assert entered.wait(5)
    r.submit(sample(),np.zeros(6),dict(reference_ns=2))
    assert r.submit(sample(),np.zeros(6),dict(reference_ns=3))=='queue_full'
    release.set();report=r.close()
    assert report['saved']==2 and report['dropped']==1
