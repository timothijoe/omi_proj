"""Read-only monitoring, freshness and non-blocking telemetry regressions."""
import json
import base64
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen, Request

import numpy as np
import pytest

from omi_hil_rl.hil.telemetry import TelemetryWriter, observation_preview, transport_snapshot
from omi_hil_rl.hil.training_monitor import Handler, TrainingMonitor, ThreadingHTTPServer


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def role(run, *, emitted=100., progress=100., phase='ACTIVE', name='actor', **extra):
    write(run/'monitor'/f'{name}.json', dict(schema='omi-monitor-v1', emitted_ns=int(emitted*1e9),
        progress_ns=int(progress*1e9), phase=phase, **extra))


@pytest.mark.parametrize('emitted,progress,phase,expected', [
    (100,100,'ACTIVE','LIVE'), (90,100,'ACTIVE','STALE'),
    (100,90,'ACTIVE','PROGRESS_STALE'), (100,100,'CLOSED','CLOSED'),
    (90,90,'FAILED','FAILED'), (105,105,'ACTIVE','CLOCK_AHEAD'),
])
def test_heartbeat_and_loop_progress_are_separate(tmp_path, emitted, progress, phase, expected):
    role(tmp_path, emitted=emitted, progress=progress, phase=phase)
    result = TrainingMonitor(tmp_path)._snapshot(100.)['actor']
    assert result['state'] == expected
    assert result['live'] == (expected == 'LIVE')


def test_historical_state_never_claims_running_or_weight_publication(tmp_path):
    write(tmp_path/'async_state.json', dict(phase='ACTIVE', policy_version=650))
    write(tmp_path/'status.json', dict(update=6502, critic_loss=.1))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = TrainingMonitor(tmp_path).snapshot()
    assert result['actor']['state'] == result['learner']['state'] == 'HISTORICAL'
    assert result['weights']['loaded'] == 650
    assert result['weights']['trained'] == 6502
    assert result['weights']['published'] is None
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_ready_imported_and_ring_occupancy_are_not_conflated(tmp_path):
    for name, count, imported in [('one', 8, True), ('two', 4, False)]:
        write(tmp_path/'episodes'/name/'ready.json', dict(count=count))
        if imported:
            write(tmp_path/'episodes'/name/'imported.json', dict(count=count))
    write(tmp_path/'periodic_episodes'/'raw'/'staging.json', dict(policy_version=3))
    write(tmp_path/'periodic_episodes'/'raw'/'audit.json', dict(ticks=20, transitions=12,
        excluded=dict(missing_causal_eef=8), success=True, success_label_recorded=False))
    write(tmp_path/'periodic_episodes'/'interrupted'/'staging.json', dict(policy_version=3))
    role(tmp_path, name='learner', phase='TRAINING', update=20, published_version=10,
         streams=dict(online=5, demonstration=9))
    role(tmp_path, policy_version=3)
    result = TrainingMonitor(tmp_path)._snapshot(100.)
    assert result['pipeline']['ready'] == 12
    assert result['pipeline']['imported'] == 8
    assert result['pipeline']['pending'] == 4
    assert result['pipeline']['pending_segments'] == 1
    assert result['pipeline']['unfinished_episodes'] == 1
    assert result['pipeline']['success_labels'] == 0
    assert result['pipeline']['usable_fraction'] == .6
    assert result['replay']['streams']['online'] == 5
    assert result['weights']['version_gap'] == 7


@pytest.mark.parametrize('contents', ['{', '[]', '{"update":NaN}', '{"schema":"wrong"}'])
def test_bad_telemetry_is_reported_without_breaking_history(tmp_path, contents):
    path = tmp_path/'monitor'/'actor.json'
    path.parent.mkdir()
    path.write_text(contents)
    result = TrainingMonitor(tmp_path).snapshot()
    assert not result['actor']['live']
    assert result['errors']


def test_writer_io_never_blocks_producer_and_close_has_final_state(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monitor = TelemetryWriter(tmp_path, 'actor', interval=.01)
    original = monitor._write
    first = True
    def delayed():
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(3.)
        original()
    monkeypatch.setattr(monitor, '_write', delayed)
    with monitor:
        assert entered.wait(3.)
        started = time.monotonic()
        monitor.update(phase='ACTIVE', policy_version=42)
        monitor.event('test_event')
        assert time.monotonic()-started < .1
        release.set()
    state = json.loads((tmp_path/'monitor'/'actor.json').read_text())
    assert state['phase'] == 'CLOSED' and state['policy_version'] == 42
    assert not monitor.thread.is_alive()
    events = (tmp_path/'monitor'/'actor.events.jsonl').read_text()
    assert 'test_event' in events and 'process_closed' in events


def test_monitor_write_failure_does_not_propagate_to_training(tmp_path, monkeypatch):
    blocked = tmp_path/'monitor'
    blocked.write_text('not a directory')
    with TelemetryWriter(tmp_path, 'learner', interval=.01) as monitor:
        monitor.update(update=17)
        deadline = time.monotonic()+3
        while monitor.error is None and time.monotonic() < deadline:
            time.sleep(.001)
        assert monitor.error
    assert not monitor.thread.is_alive()


def test_preview_cache_has_its_own_rate_and_clears_when_input_is_missing(tmp_path, monkeypatch):
    import omi_hil_rl.hil.telemetry as module
    calls = []
    def render(obs, stamp):
        calls.append(stamp)
        return dict(reference_ns=stamp)
    monkeypatch.setattr(module, 'observation_preview', render)
    monitor = TelemetryWriter(tmp_path, 'actor')
    monitor.preview({}, 1)
    monitor._write()
    monitor.preview({}, 2)
    monitor._write()
    assert calls == [1]
    monitor.preview_at = time.monotonic()-2
    monitor._write()
    assert calls == [1, 2]
    monitor.preview(None, None)
    monitor._write()
    assert 'preview' not in json.loads((tmp_path/'monitor'/'actor.json').read_text())


def observation():
    return dict(rgb=np.zeros((10,3,128,128),np.uint8), wrist_rgb=np.zeros((10,3,128,128),np.uint8),
        camera_mask=np.ones((10,2),np.float32), history_mask=np.ones(10,np.uint8),
        tactile=np.zeros((10,10,16,24),np.float32), state=np.zeros((10,14),np.float32))


def test_exact_input_preview_masks_and_source_arrays_stay_unchanged():
    from PIL import Image
    obs = observation()
    obs['rgb'][-1,0] = 255
    obs['camera_mask'][-1,1] = 0
    result = observation_preview(obs, 42)
    assert result['reference_ns'] == 42 and result['history_valid'] == 10
    assert 'rgb' in result['images'] and 'wrist_rgb' not in result['images']
    assert len(result['images']) == 7
    pixels = np.asarray(Image.open(BytesIO(base64.b64decode(result['images']['rgb'].split(',')[1]))))
    assert pixels[0, 0].tolist() == [255, 0, 0]
    assert np.all(obs['rgb'][-1,0] == 255) and not obs['tactile'].any()


def test_sensor_receipt_freshness_and_ingress_rejection_are_distinct():
    runtime = SimpleNamespace(topics={'/rgb':'rgb','/eef':'eef'},
        latest={'rgb':dict(receive_ns=990_000_000, accepted=False, header_age_ms=600., reason='old_header'),
                'eef':dict(receive_ns=900_000_000, accepted=True, header_age_ms=2.)},
        counts={'rgb':10,'eef':20}, accepted={'rgb':0,'eef':20},
        rgb_max_age_ns=500_000_000, contract=dict(eef_max_age_ns=50_000_000,max_age_ns=250_000_000))
    transport = SimpleNamespace(runtime=runtime, connected=True, pad=SimpleNamespace(buttons={311:True}),
        latest=None, node=SimpleNamespace(get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=1_000_000_000))))
    result = transport_snapshot(transport)
    assert result['sensors'][0]['state'] == 'REJECTED'
    assert result['sensors'][1]['state'] == 'STALE'
    assert result['gamepad']['rb'] and not result['observation']['ready']


def test_http_assets_tick_review_and_no_write_api(tmp_path):
    episode = tmp_path/'periodic_episodes'/'example'
    write(episode/'staging.json', dict(policy_version=2))
    write(episode/'audit.json', dict(ticks=1, transitions=0, excluded=dict(missing_causal_eef=1)))
    write(episode/'pairing.json', {})
    # Pairing is an array in the existing review format.
    (episode/'pairing.json').write_text('["matched_not_execution_confirmed"]')
    np.savez_compressed(episode/'000000.npz', metadata=np.asarray(json.dumps(dict(observation_present=True,
        observation_reference_ns=100,command_send_ns=110,command_id='hil:one',action_source='human'))),
        **{'observation__'+k:v for k,v in observation().items()})
    monitor = TrainingMonitor(tmp_path)
    server = ThreadingHTTPServer(('127.0.0.1',0),lambda *a,**k:Handler(*a,monitor=monitor,**k))
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        for route in ['/', '/monitor.css', '/monitor.js', '/api/state']:
            with urlopen(base+route) as response:
                assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
        with urlopen(base+'/api/tick?episode=example&index=0&slot=9') as response:
            tick = json.load(response)
        assert tick['image'].startswith('data:image/png;base64,') and tick['command_id'] == 'hil:one'
        assert not tick['in_training'] and tick['imported'] is None
        for route,code in [('/api/tick?episode=..&index=0',400),('/api/tick?episode=example&index=0&slot=10',400),('/../config.json',404)]:
            with pytest.raises(HTTPError) as exc:
                urlopen(base+route)
            assert exc.value.code == code
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base+'/api/state',data=b'{}',method='POST'))
        assert exc.value.code == 501
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3.)


def test_dashboard_import_has_no_torch_or_ros_dependency():
    result = subprocess.run([sys.executable,'-c',
        'import sys; import omi_hil_rl.hil.training_monitor; assert "torch" not in sys.modules; assert "rclpy" not in sys.modules'],
        capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_protection_status_subscription_is_read_only_and_absence_is_unknown():
    from omi_hil_rl.hil.ros_transport import RosTransport
    transport = RosTransport.__new__(RosTransport)
    assert not hasattr(transport, 'guard_status')
    transport._guard_status(SimpleNamespace(data='not JSON'))
    assert not hasattr(transport, 'guard_status')
    transport._guard_status(SimpleNamespace(data='{"enabled":true,"state":"latched"}'))
    assert transport.guard_status['state'] == 'latched'
    assert transport.guard_status['enabled']
    assert transport.guard_status['observed_ns'] > 0


def test_real_learner_reports_import_updates_publication_and_exit(tmp_path):
    import torch
    from omi_hil_rl.hil.config import HILConfig
    from omi_hil_rl.hil.environment import FakeTransport, RealHILEnv
    from omi_hil_rl.hil.exchange import EpisodeSpool
    from omi_hil_rl.hil.learner import run_learner
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        config = HILConfig(review='auto')
        env = RealHILEnv(FakeTransport(config, success_step=1), config)
        obs, reset = env.reset()
        nxt, reward, terminated, truncated, info = env.step(np.zeros(6, np.float32))
        info['action_source'] = 'human'  # Synthetic fixture, not a physical demonstration.
        spool = EpisodeSpool(tmp_path, reset['episode'], config.replay_contract())
        spool.append(obs, nxt, reward, terminated, truncated, info)
        spool.finish(True)
        env.close()
        run_learner(tmp_path, config, recipe=dict(encoder='synthetic-test'), capacity=8,
                    batch_size=2, updates=2, publish_every=1)
        state = TrainingMonitor(tmp_path).snapshot()
        learner = state['learner']['data']
        assert state['learner']['state'] == 'CLOSED'
        assert learner['update'] == learner['published_version'] == 2
        assert learner['actor_updates_this_process'] == 1
        assert learner['imported_this_process'] == 1
        assert state['pipeline']['imported'] == 1 and state['pipeline']['pending'] == 0
        assert any(event['kind'] == 'weights_published' for event in state['events'])
    finally:
        torch.set_num_threads(previous)
