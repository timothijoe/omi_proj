import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from omi_hil_rl.real.grid_live_v2_core import (
    Arrival, NS, diagnostics_image, header_stamp_cdr, panels, panel_health, render_panel, held_roi,
)

ROOT = Path(__file__).resolve().parents[1]


def test_original_viewer_files_preserved():
    manifest = json.loads((ROOT/'manifests/live-grid-viewer-v1.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize('endian,identifier', [('<', b'\0\1'), ('>', b'\0\0')])
def test_probe_reads_only_header_and_handles_invalid_prefix(endian, identifier):
    payload = identifier+b'\0\0'+struct.pack(endian+'iI', 123, 456)+b'large opaque image'
    assert header_stamp_cdr(payload) == 123000000456
    assert header_stamp_cdr(payload[:10]) is None
    assert header_stamp_cdr(b'\0\7'+payload[2:]) is None
    assert header_stamp_cdr(identifier+b'\0\0'+struct.pack(endian+'iI', 0, 1000000000)) is None


def test_arrival_probe_does_not_confuse_old_source_clock_with_local_loss():
    item = Arrival()
    for i in range(31):
        item.receive(10**9, 10**9+i*100_000_000)
    report = item.report(4*10**9, 100*10**9)
    assert report['state'] == 'RECEIVING'
    assert report['hz'] == 10
    assert report['header_age_ms'] == 99000
    assert report['header_repeats'] == 30
    assert report['payload_validated'] is False
    assert item.report(5*10**9, 101*10**9)['state'] == 'STALE'
    item.receive(500000000, 6*10**9)
    assert item.report(6*10**9, 102*10**9)['header_regressions'] == 1
    assert item.report(6*10**9, 102*10**9)['max_gap_ms'] == 2000
    assert item.report(10*10**9, 106*10**9)['hz'] == 0


def test_slow_renderer_and_dead_worker_distinguished_from_source():
    status = dict(state='OK', render_started_mono_ns=10**9)
    assert panel_health(status, 1700000000, 1800000000) == 'RENDER_BUSY'
    assert panel_health(status, 1700000000, 4*10**9) == 'WORKER_SILENT'
    assert panel_health(dict(state='BAD_DATA'), 1700000000, 1800000000) == 'BAD_DATA'
    assert panel_health(dict(state='OK', publish_started_mono_ns=10**9),
                        1700000000, 1800000000) == 'PUBLISH_BUSY'


def test_derived_pixels_use_existing_fixed_conventions(monkeypatch):
    from omi_hil_rl.real.grid_recorded_review import vector_preview
    from omi_hil_rl.real.recorded_observation import camera_preview
    monkeypatch.setattr('omi_hil_rl.real.ros_topics.decode_image_message', lambda m: m)
    lookup = {p.key: p for p in panels()}
    field = np.zeros((16, 24, 2), np.float32)
    field[:, :, 0] = .25
    original = field.copy()
    np.testing.assert_array_equal(np.asarray(render_panel(lookup['a_deformation'], field)), vector_preview(field)[0])
    np.testing.assert_array_equal(field, original)
    rgb = np.arange(480*640*3, dtype=np.uint8).reshape(480, 640, 3)
    np.testing.assert_array_equal(np.asarray(render_panel(lookup['camera_roi'], rgb)), camera_preview(rgb)[0])
    depth = np.zeros((16, 24), np.float32)
    assert render_panel(lookup['b_depth'], depth).getpixel((0, 0)) == (0, 0, 255)
    with pytest.raises(ValueError):
        render_panel(lookup['a_deformation'], np.full((16, 24, 2), np.nan))
    with pytest.raises(ValueError):
        render_panel(lookup['b_depth'], np.zeros((24, 16)))


def test_rviz_direct_images_and_separate_outputs():
    import yaml
    from omi_hil_rl.real.grid_live_v2 import rviz_config
    config = rviz_config(ROOT, SimpleNamespace(wrist_topic='/custom/wrist', model_mode='none'))
    displays = {d['Name']: d for d in config['Visualization Manager']['Displays']}
    assert displays['External original']['Topic']['Value'] == '/camera/camera/color/image_raw'
    assert displays['Wrist image (see topic)']['Topic']['Value'] == '/custom/wrist'
    assert displays['A deformation']['Topic']['Value'] == NS+'/panels/a_deformation'
    assert not displays['Corrected Stand (display only)']['Enabled']
    assert all(d['Class'] in ('rviz_default_plugins/Interact', 'rviz_default_plugins/MoveCamera')
               for d in config['Visualization Manager']['Tools'])
    assert '/omi/live_grid/dashboard' not in yaml.safe_dump(config)
    assert all(p.topic.startswith(NS) for p in panels() if p.kind != 'direct')
    assert len(panels()) == 9
    assert not {'Wrist full (optional)', 'A raw', 'B raw'} & displays.keys()
    assert displays['EEF and control signals']['Topic']['Value'] == NS+'/control_bar'


def test_diagnostics_renders_missing_and_stalled_probe():
    image = diagnostics_image({}, panels(), 10**9, None)
    assert image.width == 1800
    assert image.height > 300


def test_stale_roi_keeps_pixels_and_does_not_mutate_good_image():
    from PIL import Image
    source = Image.new('RGB', (128, 128), (22, 44, 88))
    held = held_roi(source, 1450)
    assert held.getpixel((64, 64)) == source.getpixel((64, 64))
    assert held.getpixel((0, 0)) != source.getpixel((0, 0))
    assert source.getpixel((0, 0)) == (22, 44, 88)


@pytest.mark.parametrize('argv', [['--hz', 'nan'], ['--hz', '31'], ['--duration', 'inf'], ['--domain', '233']])
def test_bad_arguments_fail_before_starting_ros(argv):
    from omi_hil_rl.real.grid_live_v2 import main
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
