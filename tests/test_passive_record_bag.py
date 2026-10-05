"""Independent recorder never owns gamepad or robot outputs."""
import json
import pytest
from omi_hil_rl.hil import record_bag


def test_passive_topics_and_clean_ctrl_c(tmp_path,monkeypatch):
    calls=[]
    class Recorder:
        def __init__(self,directory,topics,all_topics=False):
            calls.append((directory,topics,all_topics))
        def check(self):raise KeyboardInterrupt
        def close(self):calls.append('closed')
    monkeypatch.setattr(record_bag,'RawBag',Recorder)
    result=record_bag.record(tmp_path/'capture')
    assert result['stop_reason']=='operator_stop'
    assert result['action_publishers']==[] and not result['reads_gamepad']
    assert not result['training_labels_generated']
    assert '/omi/controller_test/decision' in calls[0][1]
    assert '/omi/tactile_grid24x16/a/wrench' in calls[0][1]
    assert '/omi/tactile_grid24x16/b/wrench' in calls[0][1]
    assert '/omi/tactile_grid24x16/a/metadata' in calls[0][1]
    assert '/omi/tactile_grid24x16/b/status' in calls[0][1]
    assert '/omi/wrist/color/image_roi/record' in calls[0][1]
    assert '/omi/wrist/metadata' in calls[0][1]
    assert not calls[0][2] and calls[-1]=='closed'
    assert json.loads((tmp_path/'capture/session.json').read_text())==result


def test_duration_custom_topic_and_failure_cleanup(tmp_path,monkeypatch):
    class Recorder:
        def __init__(self,directory,topics,all_topics=False):
            assert '/my/manual' in topics and '/extra/sensor' in topics
        def check(self):raise RuntimeError('recording exited')
        def close(self):closed.append(True)
    closed=[]
    monkeypatch.setattr(record_bag,'RawBag',Recorder)
    with pytest.raises(RuntimeError,match='recording exited'):
        record_bag.record(tmp_path/'failed',command_topic='/my/manual',extra_topics=['/extra/sensor'],duration=10)
    assert closed and json.loads((tmp_path/'failed/session.json').read_text())['stop_reason']=='error'
    with pytest.raises(ValueError):record_bag.record(tmp_path/'bad',duration=0)


def test_duration_stops_without_operator(tmp_path,monkeypatch):
    clock=[0.];checks=[]
    class Recorder:
        def __init__(self,*args,**kwargs):pass
        def check(self):checks.append(clock[0])
        def close(self):pass
    monkeypatch.setattr(record_bag,'RawBag',Recorder)
    monkeypatch.setattr(record_bag.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(record_bag.time,'sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    result=record_bag.record(tmp_path/'timed',duration=.3)
    assert result['stop_reason']=='duration_elapsed'
    assert result['elapsed_after_ready_s']==pytest.approx(.3)
    assert len(checks)==3
