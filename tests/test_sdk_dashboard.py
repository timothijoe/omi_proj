from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from omi_sensors.config import load_config
from omi_sensors.dashboard import CORE, DashboardState, decode_image, render
from omi_sensors.dashboard_launcher import validate_bag

ROOT = Path(__file__).resolve().parents[1]


def config():
    return load_config(ROOT / "ros2/omi_sensors/config/sensors.example.json")


def sample(stamp=10, fid=1):
    images = {"raw": np.zeros((32, 48, 3), np.uint8), "infer": np.zeros((32, 48), np.uint8),
              "deformation": np.ones((32, 48, 2), np.float32), "shear": np.zeros((32, 48, 2), np.float32)}
    meta = dict(schema_version=2, side="a", source_timestamp_ns=stamp, frame_id=fid, valid=True,
                field_source="sdk_direct", identity={"serial": "test", "physical_side": "right"},
                baseline_id="unknown_vendor_managed", timestamp_kind="host_receive_not_exposure",
                fields={k: dict(shape=list(v.shape), dtype=str(v.dtype)) for k, v in images.items()})
    return dict(images, metadata=meta)


def feed(state, data=None, stamp=10, now=1.0):
    data = sample(stamp) if data is None else data
    for kind, value in data.items():
        state.add("a", kind, stamp, value, now)
    return data


def test_exact_stamp_join_optional_fields_do_not_block():
    state = DashboardState(config())
    data = sample()
    for kind in CORE - {"shear"}:
        state.add("a", kind, 10, data[kind], 1.0)
    state.add("a", "shear", 11, data["shear"], 1.0)
    assert not state.samples
    state.add("a", "shear", 10, data["shear"], 1.0)
    assert state.summary(1.1)["sides"]["a"]["state"] == "VALID"
    assert state.summary(2.0)["sides"]["a"]["state"] == "STALE"
    assert state.summary(1.1)["sides"]["b"]["state"] == "WAITING"
    assert "depth" not in state.samples["a"]["data"]


def test_schema1_is_rejected_and_not_mistaken_for_sdk():
    state = DashboardState(config())
    data = sample()
    data["metadata"]["schema_version"] = 1
    feed(state, data)
    assert state.summary(1.0)["sides"]["a"]["state"] == "INVALID"
    assert not state.samples


@pytest.mark.parametrize("change", [
    lambda d: d["metadata"].update(field_source="image_reconstruction"),
    lambda d: d["metadata"].update(valid=False),
    lambda d: d["metadata"]["fields"]["deformation"].update(shape=[1, 1, 2]),
    lambda d: d.update(deformation=np.full((32, 48, 2), np.nan, np.float32)),
    lambda d: d.update(shear=np.zeros((32, 48), np.float32)),
])
def test_invalid_data(change):
    state = DashboardState(config())
    data = sample()
    change(data)
    feed(state, data)
    assert not state.samples
    assert state.summary(1.0)["sides"]["a"]["state"] == "INVALID"


def test_loop_clears_prior_frames_without_losing_current_images():
    state = DashboardState(config())
    feed(state, sample(100, 100), stamp=100)
    feed(state, sample(10, 1), stamp=10, now=2)
    assert state.epochs["a"] == 1
    assert state.samples["a"]["stamp"] == 10
    assert list(state.pending["a"]) == [10]
    for stamp in range(200, 240):
        state.add("a", "raw", stamp, np.zeros((4, 4), np.uint8), 3)
    assert len(state.pending["a"]) == 8


def test_render_is_pure_and_synthetic_is_explicit():
    state = DashboardState(config())
    data = sample()
    data["metadata"]["field_source"] = "synthetic"
    feed(state, data)
    state.add_camera(20, np.zeros((480, 640, 3), np.uint8), 1.0)
    a, status = render(state, 1.1)
    b, stale = render(state, 3.0)
    assert a.shape == (1000, 1536, 3) and a.dtype == np.uint8
    assert status["sides"]["a"]["state"] == "SYNTHETIC"
    assert stale["sides"]["a"]["state"] == "STALE"
    assert np.any(a != b)
    np.testing.assert_array_equal(data["deformation"], 1)


@pytest.mark.parametrize("encoding,pixels,expected", [
    ("bgr8", [1, 2, 3], [3, 2, 1]), ("bgra8", [1, 2, 3, 4], [3, 2, 1]),
    ("rgb8", [1, 2, 3], [1, 2, 3]), ("rgba8", [1, 2, 3, 4], [1, 2, 3]),
])
def test_color_decoding(encoding, pixels, expected):
    msg = SimpleNamespace(encoding=encoding, width=1, height=1, is_bigendian=False,
                          step=len(pixels) + 2, data=bytes(pixels + [99, 99]))
    np.testing.assert_array_equal(decode_image(msg), [[expected]])


def test_bigendian_vector_and_invalid_payload():
    msg = SimpleNamespace(encoding="32FC2", width=1, height=1, is_bigendian=True, step=12,
                          data=np.array([2, -4, 99], dtype=">f4").tobytes())
    np.testing.assert_array_equal(decode_image(msg), [[[2, -4]]])
    msg.step = 8
    with pytest.raises(ValueError):
        decode_image(msg)


def test_old_bag_rejected_before_launch(tmp_path):
    yaml = pytest.importorskip("yaml")
    metadata = {"rosbag2_bagfile_information": {"topics_with_message_count": [
        {"topic_metadata": {"name": "/tj/dm_sensor/a_raw", "type": "sensor_msgs/msg/Image"}, "message_count": 100}]}}
    (tmp_path / "metadata.yaml").write_text(yaml.safe_dump(metadata))
    with pytest.raises(ValueError, match="view_observation_bag.sh"):
        validate_bag(tmp_path, config())


def test_disabled_panels():
    cfg = config()
    cfg["tactile"]["enabled"] = False
    assert DashboardState(cfg).summary(0)["sides"]["a"]["state"] == "DISABLED"


def test_renderer_matches_frozen_renderer(monkeypatch):
    import importlib.util
    import sys
    from omi_sensors.dashboard_vectors import render_vector_field
    # Read the frozen standalone renderer without importing the RL package/Gym.
    spec = importlib.util.spec_from_file_location("frozen_vector_renderer", ROOT / "src/omi_hil_rl/real/tactile_vectors.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    frozen = module.render_vector_field
    field = np.random.default_rng(7).normal(size=(64, 64, 2)).astype(np.float32)
    np.testing.assert_array_equal(render_vector_field(field)[0], frozen(field)[0])


def test_completed_sample_is_not_mutated_by_duplicates_or_caller():
    state = DashboardState(config())
    data = feed(state)
    data["metadata"]["identity"]["serial"] = "changed"
    state.add("a", "deformation", 10, np.zeros((8, 8, 2), np.float32), 1.1)
    assert state.samples["a"]["data"]["deformation"].shape == (32, 48, 2)
    assert state.samples["a"]["data"]["metadata"]["identity"]["serial"] == "test"


def test_fresh_data_with_device_failure_is_visibly_warned():
    state = DashboardState(config())
    feed(state)
    state.add("a", "status", 0, {"state": "retrying", "error": "disconnected"}, 1.0)
    assert state.summary(1.1)["sides"]["a"]["state"] == "DEVICE_WARNING"


def test_default_native_viewer_is_isolated_from_legacy_domain():
    cfg = load_config(ROOT / "ros2/omi_sensors/config/sdk_dashboard.example.json")
    assert cfg["domain_id"] == 88
    assert 'sdk_dashboard.example.json' in (ROOT / "scripts/view_sdk_observation.sh").read_text()
