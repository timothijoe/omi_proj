"""Best-effort, bounded monitoring snapshots. Never part of control or replay."""
from collections import deque
from io import BytesIO
import base64
import json
import os
from pathlib import Path
import threading
import time
import uuid


class TelemetryWriter:
    """Producers only replace in-memory state; the worker owns all monitor I/O.

    A fresh worker heartbeat does not imply the control/training loop progressed:
    progress_ns is advanced only by a producer. Observations are immutable after
    publication by StackObservations; the worker holds at most one reference.
    Monitoring errors are reported on stderr and never affect robot commands.
    """
    def __init__(self, run, role, interval=.5):
        if role not in ('actor', 'learner') or interval <= 0:
            raise ValueError('invalid telemetry role or interval')
        self.directory = Path(run) / 'monitor'
        self.role, self.interval = role, interval
        self.session = uuid.uuid4().hex
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.data = dict(phase='INITIALIZING', progress_ns=time.time_ns())
        self.events = deque(maxlen=128)
        self.observation = None
        self.preview_cache, self.preview_at = None, 0.
        self.error = None
        self.thread = threading.Thread(target=self._work, name=f'{role}-monitor', daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def update(self, **values):
        # Values must be producer-owned snapshots, not mutable runtime objects.
        with self.lock:
            self.data.update(values, progress_ns=time.time_ns())

    def preview(self, observation, reference_ns):
        with self.lock:
            self.observation = (observation, reference_ns) if observation is not None else None

    def event(self, kind, **values):
        with self.lock:
            self.events.append(dict(time_ns=time.time_ns(), kind=kind, **values))

    def __exit__(self, typ, value, traceback):
        self.update(phase='FAILED' if typ and typ is not KeyboardInterrupt else 'CLOSED')
        if value:
            self.update(error=str(value))
        self.event('process_closed', error=str(value) if value else None)
        self.stop.set()
        self.thread.join(timeout=3.)

    def _write(self):
        with self.lock:
            snapshot = dict(self.data, schema='omi-monitor-v1', role=self.role,
                            session=self.session, pid=os.getpid(), emitted_ns=time.time_ns())
            events, self.events = list(self.events), deque(maxlen=128)
            observation = self.observation
        self.directory.mkdir(parents=True, exist_ok=True)
        if observation is None:
            self.preview_cache = None
        elif self.preview_cache is None or time.monotonic()-self.preview_at >= 1.:
            try:
                self.preview_cache = observation_preview(*observation)
                self.preview_at = time.monotonic()
            except Exception as exc:
                self.preview_cache = None
                snapshot['preview_error'] = repr(exc)
        if self.preview_cache is not None:
            snapshot['preview'] = self.preview_cache
        snapshot['writer_error'] = self.error
        temporary = self.directory / f'.{self.role}.{self.session}.tmp'
        try:
            temporary.write_text(json.dumps(snapshot, allow_nan=False), encoding='utf-8')
            temporary.replace(self.directory / f'{self.role}.json')
        finally:
            temporary.unlink(missing_ok=True)
        if events:
            with (self.directory / f'{self.role}.events.jsonl').open('a', encoding='utf-8') as stream:
                for event in events:
                    stream.write(json.dumps(dict(event, role=self.role, session=self.session), allow_nan=False) + '\n')

    def _work(self):
        while True:
            try:
                self._write()
                self.error = None
            except Exception as exc:
                error = repr(exc)
                if self.error != error:
                    import sys
                    print(f'MONITOR_{self.role.upper()}: {error}', file=sys.stderr, flush=True)
                self.error = error
            if self.stop.wait(self.interval):
                try:
                    self._write()
                except Exception:
                    pass  # Best effort; stale snapshots are never treated as live.
                return


def observation_preview(obs, reference_ns):
    """Small images of the exact latest policy input, built off the control loop."""
    import numpy as np
    from PIL import Image
    from omi_hil_rl.real.tactile_vectors import render_vector_field

    def encode(pixels):
        output = BytesIO()
        Image.fromarray(pixels).save(output, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()

    images = {}
    valid = bool(obs['history_mask'][-1])
    for side, key in enumerate(('rgb', 'wrist_rgb')):
        if valid and obs['camera_mask'][-1, side]:
            images[key] = encode(np.asarray(obs[key][-1]).transpose(1, 2, 0))
    if valid:
        touch = np.asarray(obs['tactile'][-1])
        for side in range(2):
            for field in range(2):
                values = touch[side*5+field*2:side*5+field*2+2].transpose(1, 2, 0)
                picture, _ = render_vector_field(np.repeat(np.repeat(values, 8, 0), 8, 1),
                    step=16, scale_px_per_unit=10., deadband=.01, max_arrow_px=12.)
                images[f'{"ab"[side]}_{("deformation", "shear")[field]}'] = encode(picture)
            scaled = np.clip(touch[side*5+4] / .3, 0, 1)
            images[f'{"ab"[side]}_depth'] = encode((np.stack((scaled, np.sqrt(scaled), 1-scaled), -1)*255).astype(np.uint8))
    return dict(reference_ns=reference_ns, generated_ns=time.time_ns(), images=images,
                history_valid=int(np.sum(obs['history_mask'])),
                camera_valid=np.sum(obs['camera_mask'], axis=0).astype(int).tolist())


def transport_snapshot(transport):
    """Cheap scalar snapshot of what the Actor actually received and selected."""
    now = transport.node.get_clock().now().nanoseconds
    runtime = transport.runtime
    mono = time.monotonic()
    previous = getattr(transport, '_monitor_counts', {})
    duration = mono - getattr(transport, '_monitor_count_time', mono)
    sensors = []
    for topic, key in runtime.topics.items():
        item = runtime.latest.get(key, {})
        receive = item.get('receive_ns')
        limit = (runtime.contract['eef_max_age_ns'] if key == 'eef' else
                 runtime.rgb_max_age_ns if key == 'rgb' else runtime.contract['max_age_ns'])
        age = (now-receive)/1e6 if receive is not None else None
        state = ('MISSING' if age is None else 'CLOCK_AHEAD' if age < 0 else
                 'STALE' if age > limit/1e6 else 'REJECTED' if not item.get('accepted') else 'LIVE')
        if getattr(runtime, 'latest_mode', False) and item.get('accepted') and (
                state in ('STALE', 'CLOCK_AHEAD') or item.get('timing_warnings')):
            state = 'TIMING_WARNING'
        sensors.append(dict(key=key, topic=topic, state=state, receive_age_ms=age,
            hz=(runtime.counts[key]-previous.get(key, runtime.counts[key]))/duration if duration > 0 else None,
            header_age_ms=item.get('header_age_ms'), received=runtime.counts[key],
            accepted=runtime.accepted[key], reason=item.get('reason')))
    transport._monitor_counts, transport._monitor_count_time = dict(runtime.counts), mono
    status = getattr(transport, 'latest_status', {})
    pipeline = getattr(transport, 'policy_pipeline', None)
    candidate = pipeline.get(transport.latest[1]) if pipeline is not None and transport.latest is not None else None
    return dict(sensors=sensors, sensor_clock_ns=now,
        observation=dict(ready=transport.latest is not None, reason=status.get('reason'),
            timing_diagnostic_only=getattr(runtime, 'latest_mode', False),
            timing_warnings=status.get('timing_warnings', []),
            inference_ms=candidate[1] if candidate is not None else None,
            history_mask=status.get('history_mask'), source_receive_age_ms=status.get('source_receive_age_ms'),
            eef_xyz_xyzw=status.get('eef_xyz_xyzw')),
        gamepad=dict(connected=transport.connected, rb=bool(transport.pad.buttons.get(311, False)),
                     home_active=getattr(transport, 'home_active', False)),
        protection=dict(getattr(transport, 'guard_status', {})),
        receiver_routes=dict(getattr(transport, 'receiver_info', {})),
        reset_outside_replay=True)
