import json
import time
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.hil.environment import InteractionUnavailable
from omi_hil_rl.hil.ros_transport import RosTransport


def test_expired_action_reports_timing_without_publishing(tmp_path):
    transport = RosTransport.__new__(RosTransport)
    transport._pump = lambda: None
    transport.connected = True
    transport.events = set()
    transport.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=151_000_000)))
    transport.action_timing = dict(age_before_inference_ms=130., inference_wall_ms=20.)
    transport.timing_report_path = tmp_path/'timing.json'
    stopped = []
    transport.stop = lambda: stopped.append(True)
    transport._publish = lambda *a: pytest.fail('expired action must never publish')
    with pytest.raises(InteractionUnavailable, match='100ms'):
        transport.interact(np.zeros(6), 0, time.monotonic()+5)
    report = json.loads(transport.timing_report_path.read_text())
    assert report['total_age_ms'] == 151
    assert report['age_before_inference_ms'] == 130
    assert report['inference_wall_ms'] == 20
    assert report['pre_send_pump_ms'] >= 0
    assert stopped == [True]
