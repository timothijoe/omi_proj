import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from omi_hil_rl.real.wrench_live import Monitor, render, review_session, positive, axis_bounds


def message(values, stamp=1_000_000_000):
    return NS(header=NS(stamp=NS(sec=stamp//10**9,nanosec=stamp%10**9),frame_id='tactile_a'),
              wrench=NS(force=NS(**dict(zip(('x','y','z'),values[:3]))),
                        torque=NS(**dict(zip(('x','y','z'),values[3:])))))


def test_record_preserves_signed_values_and_both_clocks():
    m=Monitor()
    values=[-1.,2.,-3.,.01,-.02,.03]
    row=m.ingest('a',message(values),1_100_000_000,3.)
    assert row['values']==values and row['header_ros_ns']==10**9
    assert row['receive_ros_ns']==1_100_000_000 and row['elapsed_s']==3.
    assert m.status(3.)['a']['values']==values
    assert m.status(3.)['a']['header_age_at_receive_ms']==100
    assert m.status(3.)['b']['state']=='WAITING'


def test_minimum_scale_is_stable_and_expands_only_at_range_boundary():
    for values in ([],[0.],[.01,-.02],[1.9,-2.]):
        assert axis_bounds(values,4.)==(-2.,2.)
    assert axis_bounds([-.49,.1],1.)==(-.5,.5)
    assert axis_bounds([2.01],4.)==(-4.,4.)
    assert axis_bounds([-3.9,3.5],4.)==(-4.,4.)
    assert axis_bounds([-4.01],4.)==(-8.,8.)


def test_recorded_review_uses_saved_scale_and_explicit_override(tmp_path,monkeypatch):
    (tmp_path/'samples.jsonl').write_text('')
    (tmp_path/'manifest.json').write_text(json.dumps(dict(force_min_span=8.,torque_min_span=2.)))
    calls=[]
    from PIL import Image
    def capture(*args,**kwargs):
        calls.append(kwargs)
        return Image.new('RGB',(10,10))
    monkeypatch.setattr('omi_hil_rl.real.wrench_live.render',capture)
    review_session(tmp_path)
    assert calls[-1]['force_min_span']==8. and calls[-1]['torque_min_span']==2.
    review_session(tmp_path,force_min_span=6.)
    assert calls[-1]['force_min_span']==6. and calls[-1]['torque_min_span']==2.


def test_invalid_and_stale_never_present_as_zero_or_live():
    m=Monitor()
    row=m.ingest('a',message([0,0,0,0,float('nan'),0]),10**9,0.)
    assert row['valid'] is False and row['values'][4] is None
    json.dumps(row,allow_nan=False)
    assert m.status(0.)['a']['state']=='INVALID'
    assert m.status(0.)['a']['values'] is None
    m.ingest('a',message([0]*6),10**9,1.)
    assert m.status(1.)['a']['state']=='LIVE'
    assert m.status(2.)['a']['state']=='STALE'
    assert m.status(2.)['a']['values'] is None
    assert m.invalid['a']==1


def test_live_history_is_bounded_without_discarding_record_rows():
    m=Monitor(window=1.)
    recorded=[m.ingest('a',message([i]*6),10**9+i,i/10) for i in range(100)]
    assert len(m.history['a'])<=11
    assert len(recorded)==100 and m.counts['a']==100
    m.status(12.)
    assert len(m.history['a'])==0


def test_saved_history_preserves_brief_peaks_and_exact_log(tmp_path,monkeypatch):
    rows=[]
    for i in range(2000):
        rows.append(dict(side='a',elapsed_s=i/100,valid=True,values=[1000. if i==777 else -2.,0,0,0,0,0]))
    data=''.join(json.dumps(r)+'\n' for r in rows)
    path=tmp_path/'samples.jsonl';path.write_text(data)
    captured={}
    from PIL import Image
    def capture(history,*args,**kwargs):
        captured.update(history)
        return Image.new('RGB',(10,10))
    monkeypatch.setattr('omi_hil_rl.real.wrench_live.render',capture)
    assert review_session(tmp_path).is_file()
    assert len(captured['a'])<=580
    assert max(p[2][0] for p in captured['a'])==1000.
    assert min(p[1][0] for p in captured['a'])==-2.
    assert path.read_text()==data


def test_render_waiting_live_invalid_and_empty_recording(tmp_path):
    m=Monitor()
    m.ingest('a',message([1,-2,3,.01,-.02,.03]),10**9,0.)
    m.ingest('a',message([float('inf'),0,0,0,0,0]),10**9,0.1)
    image=render(m.history,m.status(.1),0.,15.,'Test')
    assert image.size==(1440,880)
    (tmp_path/'samples.jsonl').write_text('')
    assert review_session(tmp_path).is_file()


@pytest.mark.parametrize('value',['nan','inf','0','-1'])
def test_positive_rejects_invalid(value):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):positive(value)
