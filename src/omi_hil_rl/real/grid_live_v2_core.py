"""Pure display/measurement contracts for the independent-panel live viewer."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

NS = '/omi/live_grid_v2'
MODEL_NS = NS + '/model'
STALE_NS = 500_000_000
HEARTBEAT_NS = 2_000_000_000


@dataclass(frozen=True)
class Panel:
    key: str
    title: str
    source: str
    kind: str = 'direct'

    @property
    def topic(self):
        return self.source if self.kind == 'direct' else f'{NS}/panels/{self.key}'


def panels(wrist_topic='/omi/wrist/color/image_roi'):
    result = [Panel('camera', 'External original', '/camera/camera/color/image_raw'),
              Panel('camera_roi', 'External ROI 128', '/camera/camera/color/image_raw', 'roi'),
              Panel('wrist', 'Wrist image (see topic)', wrist_topic)]
    for side in 'ab':
        for kind in ('deformation', 'shear', 'depth'):
            result.append(Panel(f'{side}_{kind}', f'{side.upper()} {kind}',
                                f'/omi/tactile_grid24x16/{side}/{kind}', kind))
    return result


def source_topics(items):
    result = dict.fromkeys((p.source for p in items), 'image')
    result['/tj/info/eef_left'] = 'pose'
    result['/tj/info/joint_feedback'] = 'joints'
    for side in 'ab':
        result[f'/omi/tactile_grid24x16/{side}/wrench'] = 'wrench'
    return result


def header_stamp_cdr(data):
    """Read ONLY the Header prefix of CDR1 Image/Pose/Jointfeedback/Wrench.

    Unknown encodings remain measurable arrivals, with unknown source time.
    This avoids deserializing/copying large image payloads in the source probe.
    """
    if len(data) < 12 or bytes(data[:2]) not in (b'\x00\x00', b'\x00\x01'):
        return None
    sec, nano = struct.unpack_from('<iI' if data[1] == 1 else '>iI', data, 4)
    return sec * 10**9 + nano if sec >= 0 and nano < 10**9 and sec * 10**9 + nano > 0 else None


class Arrival:
    def __init__(self):
        self.count = 0
        self.times = deque(maxlen=512)
        self.gaps = deque(maxlen=512)
        self.header = None
        self.last = None
        self.max_gap_ns = 0
        self.header_repeats = 0
        self.header_regressions = 0

    def receive(self, stamp, mono):
        if self.last is not None:
            gap = max(0, mono - self.last)
            self.gaps.append((mono, gap))
            self.max_gap_ns = max(self.max_gap_ns, gap)
        if stamp is not None and self.header is not None:
            self.header_repeats += int(stamp == self.header)
            self.header_regressions += int(stamp < self.header)
        self.count += 1
        self.last, self.header = mono, stamp
        self.times.append(mono)

    def report(self, mono, wall):
        times = [t for t in self.times if mono - t <= 3 * 10**9]
        age = None if self.last is None else max(0, mono - self.last) / 1e6
        hz = (len(times) - 1) * 1e9 / (times[-1] - times[0]) if len(times) > 1 else 0.
        return dict(count=self.count, hz=hz, receive_age_ms=age,
                    state='WAITING' if age is None else 'STALE' if age > STALE_NS/1e6 else 'RECEIVING',
                    max_gap_ms=self.max_gap_ns/1e6,
                    recent_max_gap_ms=max((g/1e6 for t, g in self.gaps if mono-t <= 3*10**9), default=0.),
                    header_age_ms=None if self.header is None else (wall-self.header)/1e6,
                    header_repeats=self.header_repeats, header_regressions=self.header_regressions,
                    payload_validated=False)


def panel_health(status, heartbeat_ns, mono):
    if heartbeat_ns is None or mono - heartbeat_ns > HEARTBEAT_NS:
        return 'WORKER_SILENT'
    started = status.get('render_started_mono_ns')
    if started is not None and mono - started > STALE_NS:
        return 'RENDER_BUSY'
    started = status.get('publish_started_mono_ns')
    if started is not None and mono - started > STALE_NS:
        return 'PUBLISH_BUSY'
    return status.get('state', 'WAITING')


def font(size=16):
    try:
        return ImageFont.truetype('DejaVuSansMono.ttf', size)
    except OSError:
        return ImageFont.load_default()


def placeholder(title, state):
    result = Image.new('RGB', (384, 256), '#151c26')
    draw = ImageDraw.Draw(result)
    draw.text((12, 25), title, font=font(18), fill='white')
    draw.text((12, 85), state, font=font(20), fill='#ffba69')
    draw.text((12, 135), 'See independent diagnostics', font=font(16), fill='white')
    return result


def held_roi(image, age_ms):
    """Retain last valid pixels for viewing, with an unmistakable stale badge."""
    result = image.convert('RGB').copy()
    draw = ImageDraw.Draw(result)
    draw.rectangle((0, 0, result.width-1, result.height-1), outline='#ff5555', width=3)
    draw.rectangle((0, 0, result.width-1, 19), fill='#9a2020')
    draw.text((4, 2), f'STALE {age_ms/1000:.1f}s', font=font(12), fill='white')
    return result


def render_panel(panel, message):
    # Shared read-only numerical conventions; no full-dashboard renderer.
    from .ros_topics import decode_image_message
    value = decode_image_message(message)
    if not np.isfinite(value).all():
        raise ValueError('Nonfinite input')
    if panel.kind == 'roi':
        from .recorded_observation import camera_preview
        if value.ndim != 3 or value.shape[2] != 3:
            raise ValueError('Expected RGB image')
        return Image.fromarray(camera_preview(value)[0])
    if panel.kind in ('deformation', 'shear'):
        from .grid_recorded_review import vector_preview
        return Image.fromarray(vector_preview(value)[0])
    if panel.kind == 'depth':
        if value.shape != (16, 24):
            raise ValueError('Expected 16x24 depth')
        u = np.clip(value / .3, 0, 1)
        rgb = (np.stack((u, np.sqrt(u), 1-u), axis=-1) * 255).astype(np.uint8)
        return Image.fromarray(rgb).resize((384, 256), Image.Resampling.NEAREST)
    raise ValueError('Direct images must be displayed by RViz')


def number(value):
    return '--' if value is None or not math.isfinite(value) else f'{value:.1f}'


def diagnostics_image(snapshot, items, mono, received_mono):
    """Small text-only display; never decodes or composites sensor images."""
    rows = []
    stale = received_mono is None or mono - received_mono > HEARTBEAT_NS
    for p in items:
        src = snapshot.get('sources', {}).get(p.source, {})
        worker = snapshot.get('workers', {}).get(p.key, {})
        output = snapshot.get('outputs', {}).get(p.key, {})
        state = 'PROBE_SILENT' if stale else src.get('state', 'WAITING')
        if not stale and p.kind != 'direct':
            state = panel_health(worker, worker.get('heartbeat_received_mono_ns'), mono)
        rows.append((p.title, src, worker, output, state, p.kind))
    # Small scalar topics remain visible without burdening any image worker.
    for topic, src in snapshot.get('sources', {}).items():
        if source_topics(items).get(topic, 'image') != 'image':
            rows.append((topic.rsplit('/', 1)[-1] if 'wrench' not in topic else topic.split('/')[-2]+' wrench',
                         src, {}, {}, 'PROBE_SILENT' if stale else src.get('state', 'WAITING'), 'direct'))
    control = snapshot.get('control_bar', {})
    control_health = 'PROBE_SILENT' if stale else panel_health(control, control.get('heartbeat_received_mono_ns'), mono)
    rows.append(('EEF / command bar', {}, control, snapshot.get('outputs', {}).get('control_bar', {}), control_health, 'derived'))
    result = Image.new('RGB', (1800, 140 + len(rows)*30), '#151c26')
    draw = ImageDraw.Draw(result)
    f = font(22)
    draw.text((10, 5), 'V2 | Independent arrival probe + panel workers | '+('PROBE SILENT' if stale else 'PROBE RECEIVING'), font=f, fill='white')
    draw.text((10, 35), 'Raw/frozen workers may retain last image: check diagnostics. Header age is NOT end-to-end latency.', font=f, fill='#ffd080')
    draw.text((10, 65), 'Hz = callbacks/outputs, NOT hardware FPS or RViz presentation FPS. Times in ms.', font=f, fill='#a9c6e5')
    draw.text((10, 105), f'{"Panel/source":<27} {"RX Hz":>6} {"RX age":>8} {"Gap3s":>7} {"Header":>9} {"Out Hz":>7} {"Draw":>8} {"RX->pub":>9}  Status', font=f, fill='white')
    for i, (title, src, worker, out, state, kind) in enumerate(rows):
        line = (f'{title[:26]:<27} {number(src.get("hz")):>6} {number(src.get("receive_age_ms")):>8} '
                f'{number(src.get("recent_max_gap_ms")):>7} {number(src.get("header_age_ms")):>9} '
                f'{number(out.get("hz")) if kind != "direct" else "direct":>7} '
                f'{number(worker.get("render_ms")):>8} {number(worker.get("receive_to_publish_ms")):>9}  {state}')
        draw.text((10, 135+i*30), line, font=f, fill='#8aefae' if state in ('RECEIVING', 'OK') else '#ffba69')
    return result
