"""Local read-only training dashboard. No ROS, torch, replay locks or publishers."""
from __future__ import annotations

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
import time
from urllib.parse import parse_qs, urlparse


class TrainingMonitor:
    def __init__(self, run, *, sensor_status=None, stale_seconds=5.):
        self.run = Path(run).resolve()
        if not self.run.is_dir():
            raise ValueError('run directory does not exist')
        if stale_seconds <= 0:
            raise ValueError('stale seconds must be positive')
        self.sensor_status = Path(sensor_status).resolve() if sensor_status else None
        self.stale_seconds = stale_seconds
        self.lock = threading.Lock()
        self.cached, self.cached_at = None, 0.

    def _read(self, path, errors):
        try:
            def reject_constant(value):
                raise ValueError('nonfinite JSON constant: '+value)
            data = json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)
            if not isinstance(data, dict):
                raise ValueError('expected a JSON object')
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            errors.append(dict(file=str(path.relative_to(self.run)) if path.is_relative_to(self.run) else str(path),
                               error=str(exc)))
            return None

    def _role(self, role, now, errors):
        path = self.run/'monitor'/f'{role}.json'
        data = self._read(path, errors)
        if data is None:
            legacy_path = self.run/('async_state.json' if role == 'actor' else 'status.json')
            legacy = self._read(legacy_path, errors)
            return dict(state='HISTORICAL' if legacy else 'UNKNOWN', data=legacy or {},
                        age_s=max(0., now-legacy_path.stat().st_mtime) if legacy else None,
                        progress_age_s=None, source=legacy_path.name, live=False)
        if (not isinstance(data, dict) or data.get('schema') != 'omi-monitor-v1' or
                not isinstance(data.get('emitted_ns'), int) or not isinstance(data.get('progress_ns'), int)):
            errors.append(dict(file=str(path), error='invalid telemetry schema'))
            return dict(state='UNKNOWN', data={}, age_s=None, progress_age_s=None, source=str(path), live=False)
        age = now-data['emitted_ns']/1e9
        progress_age = now-data['progress_ns']/1e9
        phase = data.get('phase')
        state = ('CLOCK_AHEAD' if min(age, progress_age) < -1. else
                 phase if phase in ('CLOSED', 'FAILED') else
                 'STALE' if age > self.stale_seconds else
                 'PROGRESS_STALE' if progress_age > self.stale_seconds else 'LIVE')
        return dict(state=state, data=data, age_s=age, progress_age_s=progress_age,
                    source=str(path.relative_to(self.run)), live=state == 'LIVE')

    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic()-self.cached_at < 1.:
                return self.cached
            result = self._snapshot(time.time())
            self.cached, self.cached_at = result, time.monotonic()
            return result

    def _snapshot(self, now):
        errors = []
        actor = self._role('actor', now, errors)
        learner = self._role('learner', now, errors)
        episodes, excluded, timing_diagnostics = [], Counter(), Counter()
        for directory in (self.run/'periodic_episodes').glob('*'):
            if not directory.is_dir():
                continue
            audit = self._read(directory/'audit.json', errors)
            staging = self._read(directory/'staging.json', errors) or {}
            if not audit and not staging:
                continue
            audit = audit or {}
            excluded.update(audit.get('excluded', {}))
            timing_diagnostics.update(audit.get('timing_diagnostics', {}))
            episodes.append(dict(id=directory.name, audited=bool(audit),
                ticks=audit['ticks'] if 'ticks' in audit else len(list(directory.glob('[0-9][0-9][0-9][0-9][0-9][0-9].npz'))),
                transitions=audit.get('transitions', 0), success=audit.get('success', False),
                success_label_recorded=audit.get('success_label_recorded', False),
                reason=audit.get('reason', 'unfinished'), excluded=audit.get('excluded', {}),
                observation_ticks=audit.get('observation_ticks'),
                timing_policy=audit.get('timing_policy', 'strict'),
                timing_diagnostics=audit.get('timing_diagnostics', {}),
                policy_version=audit.get('policy_version', staging.get('policy_version')),
                modified_ns=(directory/'staging.json').stat().st_mtime_ns if staging else directory.stat().st_mtime_ns))
        episodes.sort(key=lambda item: item['modified_ns'], reverse=True)
        ready_count = imported_count = pending_segments = 0
        oldest_pending = None
        for ready in (self.run/'episodes').glob('*/ready.json'):
            manifest = self._read(ready, errors)
            if not manifest:
                continue
            count = manifest.get('count', 0)
            ready_count += count
            if (ready.parent/'imported.json').is_file():
                imported_count += count
            else:
                pending_segments += 1
                stamp = ready.stat().st_mtime
                oldest_pending = stamp if oldest_pending is None else min(oldest_pending, stamp)
        complete = [item for item in episodes if item['audited']]
        ticks = sum(item['ticks'] for item in complete)
        transitions = sum(item['transitions'] for item in complete)
        events = []
        for path in (self.run/'monitor').glob('*.events.jsonl'):
            try:
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size-65536))
                    for line in stream.read().splitlines():
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            continue
            except OSError as exc:
                errors.append(dict(file=str(path), error=str(exc)))
        events.sort(key=lambda item: item.get('time_ns', 0), reverse=True)
        sensor_bridge = None
        if self.sensor_status:
            path = self.sensor_status/'status.json'
            data = self._read(path, errors)
            if data:
                age = now-path.stat().st_mtime
                sensor_bridge = dict(data=data, age_s=age, live=0 <= age < self.stale_seconds)
        actor_data, learner_data = actor['data'], learner['data']
        session = self._read(self.run/'async_session.json', errors) or {}
        manifest = self._read(self.run/'replay'/'manifest.json', errors) or {}
        published = learner_data.get('published_version')
        version = actor_data.get('policy_version')
        return dict(schema='omi-training-monitor-v1', now_ns=int(now*1e9), run=str(self.run),
            actor=actor, learner=learner, sensor_bridge=sensor_bridge, errors=errors,
            weights=dict(loaded=version, trained=learner_data.get('update'), published=published,
                published_ns=learner_data.get('published_ns'),
                version_gap=published-version if isinstance(published, int) and isinstance(version, int) else None,
                reload_episodes=actor_data.get('reload_episodes'),
                episodes_until_check=max(0, actor_data.get('reload_episodes', 10)-
                    (actor_data.get('complete_episodes', 0)-actor_data.get('last_reload_check', 0))) if actor_data else None),
            pipeline=dict(complete_episodes=len(complete), unfinished_episodes=len(episodes)-len(complete),
                ticks=ticks, transitions=transitions, excluded=dict(excluded),
                timing_diagnostics=dict(timing_diagnostics),
                usable_fraction=transitions/ticks if ticks else None,
                ready=ready_count, imported=imported_count, pending=ready_count-imported_count,
                pending_segments=pending_segments, oldest_pending_s=now-oldest_pending if oldest_pending else None,
                success_labels=sum(bool(item['success_label_recorded']) for item in complete)),
            replay=dict(streams=learner_data.get('streams', {}), capacities=manifest.get('capacities'),
                        clean=manifest.get('clean'), backend=manifest.get('backend'),
                        cache=learner_data.get('replay')),
            disk_free_gib=shutil.disk_usage(self.run).free/2**30,
            session=dict(control_mode=session.get('control_mode'), replay_backend=session.get('replay_backend'),
                         action_semantics=session.get('contract', {}).get('action_semantics')),
            episodes=episodes, events=events[:40])

    def tick(self, episode_id, index, slot):
        from .periodic_review import PeriodicReview
        # Resolve only an indexed ID; arbitrary filesystem paths are never accepted.
        review = PeriodicReview(self.run)
        for i, episode in enumerate(review.episodes):
            if episode['directory'].name == episode_id:
                return review.tick(i, index, slot)
        raise ValueError('unknown episode')


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, monitor, **kwargs):
        self.monitor = monitor
        super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            url, assets = urlparse(self.path), Path(__file__).with_name('static')
            if url.path == '/':
                payload, kind = (assets/'training_monitor.html').read_bytes(), 'text/html; charset=utf-8'
            elif url.path in ('/monitor.js', '/monitor.css'):
                name = 'training_monitor.'+url.path.rsplit('.', 1)[1]
                payload = (assets/name).read_bytes()
                kind = 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
            elif url.path == '/api/state':
                payload, kind = json.dumps(self.monitor.snapshot(), allow_nan=False).encode(), 'application/json'
            elif url.path == '/api/tick':
                query = parse_qs(url.query)
                value = self.monitor.tick(query['episode'][0], int(query['index'][0]), int(query.get('slot', ['9'])[0]))
                payload, kind = json.dumps(value, allow_nan=False).encode(), 'application/json'
            elif url.path == '/sensor-dashboard.png' and self.monitor.sensor_status:
                payload, kind = (self.monitor.sensor_status/'dashboard.png').read_bytes(), 'image/png'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, KeyError, IndexError, OSError) as exc:
            self.send_error(400, str(exc))

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8768)
    parser.add_argument('--sensor-status', type=Path, help='optional existing live grid viewer output directory')
    parser.add_argument('--stale-seconds', type=float, default=5.)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 0 < args.stale_seconds < float('inf'):
        parser.error('invalid port or stale-seconds')
    monitor = TrainingMonitor(args.run, sensor_status=args.sensor_status, stale_seconds=args.stale_seconds)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), lambda *a, **k: Handler(*a, monitor=monitor, **k))
    print(f'OMI TRAINING MONITOR · READ ONLY: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
