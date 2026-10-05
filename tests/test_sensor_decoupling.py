from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ros2/omi_sensors'))
from omi_sensors.independent_tactile import IndependentReader
from omi_sensors.frame_queue import FrameQueue
from omi_sensors.tactile import snapshot, IncompleteFrame
from omi_hil_rl.training.sensor_alignment import AuditedObservations, prefer_record_topic
from omi_hil_rl.training.eef_bc_grid import GridProfile


class SDK:
    def getForce(self): return np.arange(6, dtype=float)
    def getDeformation2D(self): return 10, np.ones((288,384,2), np.float32)
    def getShear(self): return 11, np.ones((288,384,2), np.float32)*2
    def getDepth(self): raise RuntimeError('depth temporarily missing')
    def getRawImg(self): raise RuntimeError('raw unavailable')
    getInferImg = getRawImg


def test_one_bad_field_does_not_discard_valid_force_and_other_frames():
    sdk = SDK()
    reader = IndependentReader(depth=True, wrench=True)
    rows = {k: reader.read(sdk, k) for k in reader.kinds}
    assert rows['depth'] is None
    assert rows['deformation'][1]['sdk_frame_id'] == 10
    assert rows['shear'][1]['sdk_frame_id'] == 11
    assert rows['wrench'][1]['sdk_frame_id'] is None
    assert rows['wrench'][1]['freshness_verified'] is False
    assert 'raw' not in reader.kinds
    np.testing.assert_array_equal(rows['shear'][0], 2)
    assert reader.counts['depth']['invalid_reads'] == 1


def test_field_dedup_and_recovery_do_not_gate_unframed_reads():
    sdk = SDK(); reader = IndependentReader(wrench=True)
    assert reader.read(sdk, 'deformation') is not None
    assert reader.read(sdk, 'deformation') is None
    reader.read(sdk, 'wrench')
    _, audit = reader.read(sdk, 'wrench')
    assert audit['changed_since_previous_read'] is False
    assert audit['new_source_frame_observed'] is False
    assert audit['source_timestamp_ns'] is None
    sdk.getDeformation2D = lambda: (12, np.ones((288,384,2), np.float32))
    assert reader.read(sdk, 'deformation')[1]['counters']['source_sequence_gaps'] == 1
    sdk.getDepth = lambda: (50, np.zeros((288,384), np.float32))
    assert reader.read(sdk, 'depth') is not None


def test_force_uses_own_frame_id_and_nonfinite_field_isolated():
    sdk = SDK();reader = IndependentReader(wrench=True)
    sdk.getForce = lambda: (999, np.ones(6))
    assert reader.read(sdk, 'wrench')[1]['sdk_frame_id'] == 999
    sdk.getShear = lambda: (11, np.full((288,384,2), np.nan, np.float32))
    assert reader.read(sdk, 'shear') is None
    assert reader.read(sdk, 'deformation') is not None


def frame(i, size=2): return (i, 0, b'x'*size, 0, 0)


def test_record_queue_preserves_fifo_until_explicit_overflow():
    q = FrameQueue('record', max_frames=3, max_bytes=6)
    for i in range(3): q.put(frame(i))
    assert [q.pop()[0] for _ in range(3)] == [0,1,2]
    assert q.stats().get('queue_overflow_drops', 0) == 0
    for i in range(4): q.put(frame(i))
    assert q.stats()['queue_overflow_drops'] == 1
    assert [q.pop()[0] for _ in range(3)] == [1,2,3]
    q.put(frame(9, 7))
    assert q.pop() is None and q.stats()['oversize_drops'] == 1


def test_latest_queue_and_byte_limit():
    q = FrameQueue('latest')
    q.put(frame(1));q.put(frame(2))
    assert q.pop()[0] == 2 and q.stats()['latest_overwrites'] == 1
    q = FrameQueue('record', max_frames=100, max_bytes=5)
    q.put(frame(1,3));q.put(frame(2,3))
    assert q.pop()[0] == 2 and q.stats()['queue_overflow_drops'] == 1


def feed(r, t, skew=0):
    for key in r.topics.values():
        if key in ('rgb','wrist_rgb'): value=np.zeros((3,128,128),np.uint8)
        elif key=='eef': value=np.array([.5,.1,.8,0,0,0,1],np.float32)
        else: value=np.zeros((1 if key.endswith('depth') else 2,16,24),np.float32)
        assert r.ingest(key,NS(stamp=t-skew if key=='b_shear' else t,value=value),t)


def runtime(**kw):
    r=AuditedObservations(GridProfile('required').CONTRACT, **kw)
    r.profile.decode=lambda k,m:(m.stamp,m.value)
    return r


def test_alignment_preserves_asynchronous_headers_and_optional_skew_guard():
    t=10**9
    r=runtime(provenance={('b_shear', t-30_000_000): {'sdk_frame_id':12}})
    feed(r,t,30_000_000)
    window,status=r.window(t)
    assert window is not None
    assert status['tactile_host_header_skew_ms']==30
    assert status['field_alignment_history'][-1]['b_shear']['sdk_frame_id']==12
    feed(r,t+100_000_000)
    _,status=r.window(t+100_000_000)
    assert status['field_alignment_history'][-2]['b_shear']['header_age_ms']==30
    assert status['field_alignment_history'][-1]['b_shear']['header_age_ms']==0
    r=runtime(max_tactile_skew_ms=20)
    feed(r,t,30_000_000)
    window,status=r.window(t)
    assert window is None and status['reason']=='tactile_host_header_skew'
    assert t not in r.history


def test_choose_only_recording_topic_and_reset_provenance_history():
    r=runtime(); prefer_record_topic(r, {'/omi/wrist/color/image_roi/record'})
    assert '/omi/wrist/color/image_roi' not in r.topics
    assert r.topics['/omi/wrist/color/image_roi/record']=='wrist_rgb'
    feed(r,2*10**9);r.window(2*10**9)
    feed(r,10**9);_,status=r.window(10**9)
    assert sum(bool(row) for row in status['field_alignment_history'])==1


@pytest.mark.parametrize('value', [-1,float('nan'),float('inf')])
def test_invalid_skew_limit(value):
    with pytest.raises(ValueError):runtime(max_tactile_skew_ms=value)
