from types import SimpleNamespace as NS
import numpy as np
from omi_hil_rl.real.grid_live_review import Monitor, render, TOPICS, REQUIRED


def msg(value,stamp=1_000_000_000,frame='base_link'):
    return NS(value=value,stamp=stamp,frame=frame)


def decoder(key,message):
    if not np.isfinite(message.value).all():raise ValueError('Nonfinite')
    return dict(value=message.value,stamp=message.stamp,frame=message.frame)


def test_missing_stale_invalid_and_clock_checks(monkeypatch):
    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.decode',decoder)
    m=Monitor();m.publishers['camera']=1
    assert m.report(10**9,10**9)['camera']['state']=='WAITING'
    m.receive('camera',msg(np.zeros((4,4,3),np.uint8)),10**9,10**9)
    assert m.report(10**9+10,10**9+10)['camera']['state']=='LIVE'
    assert m.report(10**9+300_000_000,10**9+300_000_000)['camera']['state']=='STALE'
    m.receive('camera',msg(np.full((4,4,3),np.nan)),10**9+1,10**9+1)
    assert m.report(10**9+1,10**9+1)['camera']['state']=='BAD_DATA'
    assert 'camera' not in m.latest
    m.receive('eef',msg(np.array([0,0,0,0,0,0,1]),frame='A_base'),10**9,10**9)
    assert m.report(10**9,10**9)['eef']['state']=='FRAME_CHECK'
    m.receive('eef',msg(np.array([0,0,0,0,0,0,1]),stamp=2*10**9),10**9,10**9)
    assert m.report(10**9,10**9)['eef']['state']=='CLOCK_AHEAD'
    m.receive('eef',msg(np.array([0,0,0,0,0,0,1])),10**9+60_000_000,10**9)
    assert m.report(10**9+60_000_000,10**9)['eef']['state']=='OLD_HEADER'


def test_external_camera_uses_local_receive_time_despite_header_clock_skew(monkeypatch):
    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.decode', decoder)
    m = Monitor()
    image = np.zeros((4, 4, 3), np.uint8)
    for source_stamp in (0, 2_000_000_000):
        m.receive('camera', msg(image, stamp=source_stamp), 1_000_000_000, 1_000_000_000)
        report = m.report(1_100_000_000, 1_100_000_000)['camera']
        assert report['state'] == 'LIVE'
        assert report['freshness_basis'] == 'local_receive'
        assert report['receive_age_ms'] == 100
        assert report['header_age_ms'] != report['receive_age_ms']
    assert m.report(1_300_000_000, 1_300_000_000)['camera']['state'] == 'STALE'


def test_external_camera_panel_labels_receive_age_without_changing_source_stamp(monkeypatch):
    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.decode', decoder)
    m = Monitor()
    m.receive('camera', msg(np.zeros((4, 4, 3), np.uint8), stamp=1),
              1_000_000_000, 1_000_000_000)
    report = m.report(1_100_000_000, 1_100_000_000)
    captured = {}

    def capture(latest, *_):
        captured['stamp'] = latest['camera']['stamp']
        from PIL import Image
        return Image.new('RGB', (1536, 1030))

    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.render', capture)
    render(m, report, 1_100_000_000, 0, 13)
    assert captured['stamp'] == 1_000_000_000
    assert m.latest['camera']['stamp'] == 1


def test_rate_window_and_optional_inputs(monkeypatch):
    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.decode',decoder)
    m=Monitor()
    for t in (10**9,1_100_000_000,1_200_000_000):m.receive('camera',msg(np.zeros((4,4,3),np.uint8),t),t,t)
    assert m.report(1_200_000_000,1_200_000_000)['camera']['hz']==10
    assert m.report(5*10**9,5*10**9)['camera']['hz']==0
    assert 'joints' not in REQUIRED and 'a_force' not in REQUIRED
    assert not any('/control/' in topic or '/action/' in topic for topic in TOPICS)


def test_missing_live_dashboard_renders():
    m=Monitor();report=m.report(10**9,10**9)
    im=render(m,report,10**9,0,13)
    assert im.size==(1536,1540)


def test_model_review_does_not_invent_pose_or_hide_frame_mismatch(monkeypatch):
    from omi_hil_rl.real.grid_live_review import model_sample
    monkeypatch.setattr('omi_hil_rl.real.grid_live_review.grid.decode',decoder)
    m=Monitor()
    assert model_sample(m,m.report(10**9,10**9),'joints') is None
    values=np.arange(14,dtype=float)/10
    joint_msg=NS(positions=values,header=NS(frame_id='',stamp=NS(sec=1,nanosec=0)))
    m.receive('joints',joint_msg,10**9,10**9)
    np.testing.assert_array_equal(model_sample(m,m.report(10**9,10**9),'joints'),values)
    assert model_sample(m,m.report(2*10**9,2*10**9),'joints') is None
    pose=np.array([.2,.3,.4,0,0,0,1])
    m.receive('eef',msg(pose,frame='A_base'),10**9,10**9)
    assert model_sample(m,m.report(10**9,10**9),'eef') is None
    m.receive('eef',msg(pose),10**9,10**9)
    report=m.report(10**9+60_000_000,10**9+30_000_000)
    assert report['eef']['state']=='OLD_HEADER'
    np.testing.assert_array_equal(model_sample(m,report,'eef'),pose)


def test_live_joint_schema_validation():
    m=Monitor()
    header=NS(frame_id='',stamp=NS(sec=1,nanosec=0))
    m.receive('joints',NS(positions=np.arange(14),header=header),10**9,10**9)
    assert m.report(10**9,10**9)['joints']['state']=='LIVE'
    for values in (np.zeros(7),np.full(14,np.nan)):
        m.receive('joints',NS(positions=values,header=header),10**9,10**9)
        assert m.report(10**9,10**9)['joints']['state']=='BAD_DATA'
        assert 'joints' not in m.latest
