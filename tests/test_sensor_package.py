"""The ROS package's pure contract tests also run in the main project's venv."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2" / "omi_sensors"))
from omi_sensors.config import load_config, camera_command, sensor_topics, positive
from omi_sensors.tactile import IncompleteFrame, snapshot, sdk_check
from omi_sensors.cli import environment, main, supervise


@pytest.fixture
def config():
    return load_config(ROOT / "ros2/omi_sensors/config/sensors.example.json")


def test_color_only_allowlist_and_command(config):
    topics = sensor_topics(config)
    assert "/camera/camera/color/camera_info" in topics
    assert "/omi/tactile/a/infer" in topics
    assert "/omi/tactile/a/metadata" in topics
    assert not any("depth" in t or "command" in t or "wrench" in t for t in topics)
    command = camera_command(config)
    assert "enable_depth:=false" in command
    assert "camera_namespace:=camera" in command
    config["realsense"]["serial"] = "123456"
    assert "serial_no:='123456'" in camera_command(config)


def test_depth_is_explicit(config):
    config["realsense"].update(enable_depth=True, align_depth=True)
    config["tactile"]["enable_depth"] = True
    assert "/camera/camera/aligned_depth_to_color/image_raw" in sensor_topics(config)
    assert "/omi/tactile/b/depth" in sensor_topics(config)


@pytest.mark.parametrize("change", [
    lambda c: c.update(domain_id=-1),
    lambda c: c["tactile"].update(enabled="false"),
    lambda c: c["realsense"].update(align_depth=True),
    lambda c: c["realsense"].update(color_profile="640x0x30"),
    lambda c: c["tactile"]["sensors"]["b"].update(pc_port=60033),
    lambda c: c.update(unrecognized="typo"),
])
def test_invalid_config(tmp_path, config, change):
    change(config)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1"])
def test_rate(value):
    with pytest.raises(ValueError):
        positive(value)


class FakeSDK:
    def __init__(self):
        self.fid = 7
        self.raw = np.zeros((8, 9), dtype=np.uint8)
        self.field = np.zeros((4, 5, 2), dtype=np.float32)

    def getRawImg(self):
        return self.fid, SimpleNamespace(img=self.raw)

    getInferImg = getRawImg

    def getDeformation2D(self):
        return self.fid, self.field

    getShear = getDeformation2D

    def getDepth(self):
        return self.fid, self.field[..., 0]

    def getForce(self):
        return np.zeros(6)


def test_snapshot_copies_and_keeps_raw_infer_separate():
    sdk = FakeSDK()
    fid, stamp, arrays, state = snapshot(sdk, depth=True, wrench=True)
    assert fid == 7 and stamp > 0
    assert arrays["deformation"].shape == (4, 5, 2)
    assert "wrench" not in arrays and state == "unframed_or_mismatched_omitted"
    sdk.raw[:] = 255
    assert arrays["raw"].max() == 0
    assert arrays["raw"] is not arrays["infer"]


def test_snapshot_rejects_mixed_frames():
    sdk = FakeSDK()
    sdk.getShear = lambda: (8, sdk.field)
    with pytest.raises(IncompleteFrame, match="different frame IDs"):
        snapshot(sdk)


def test_snapshot_rejects_bad_values():
    sdk = FakeSDK()
    sdk.field[0, 0] = np.nan
    with pytest.raises(IncompleteFrame, match="nonfinite"):
        snapshot(sdk)


def test_sdk_version_guard_before_import(config):
    config["tactile"]["sdk_python"] = "3.99"
    with pytest.raises(RuntimeError, match="Obtain a matching SDK"):
        sdk_check(config["tactile"])


def test_plan_does_not_load_sdk_or_ros(capsys):
    assert main(["--config", str(ROOT / "ros2/omi_sensors/config/sensors.example.json"), "plan"]) == 0
    assert "record_topics" in json.loads(capsys.readouterr().out)
    assert "dmrobotics" not in sys.modules


def test_isolated_environment(config):
    env = environment(config)
    assert env["ROS_DOMAIN_ID"] == "87" and env["ROS_LOCALHOST_ONLY"] == "1"


def test_record_refuses_existing_directory(tmp_path):
    assert main(["--config", str(ROOT / "ros2/omi_sensors/config/sensors.example.json"), "record", str(tmp_path)]) == 2
    assert not (tmp_path / "session.json").exists()


def test_supervisor_propagates_child_error():
    assert supervise([[sys.executable, "-c", "raise SystemExit(7)"]], {}) == 7


def test_bag_path_escape(tmp_path):
    pytest.importorskip("yaml")
    from omi_sensors.cli import playback_source
    (tmp_path / "metadata.yaml").write_text("rosbag2_bagfile_information:\n  relative_file_paths: [../outside.db3]\n")
    with pytest.raises(ValueError, match="outside bag"):
        with playback_source(tmp_path):
            pass


def test_frame_matched_force():
    sdk = FakeSDK()
    sdk.getForce = lambda: (7, np.arange(6, dtype=float))
    _, _, arrays, state = snapshot(sdk, wrench=True)
    assert state == "frame_id_matched_units_unverified"
    np.testing.assert_array_equal(arrays["wrench"], np.arange(6))


def test_empty_recording_report(tmp_path):
    pytest.importorskip("yaml")
    from omi_sensors.cli import recording_report
    report = recording_report(tmp_path, ["/omi/tactile/a/raw"])
    assert not report["all_topics_present"]
    assert report["missing_or_empty_topics"] == ["/omi/tactile/a/raw"]


def test_file_compressed_bag_never_changes_source(tmp_path):
    import shutil
    import subprocess
    yaml = pytest.importorskip("yaml")
    if not shutil.which("zstd"):
        pytest.skip("zstd not installed")
    from omi_sensors.cli import playback_source
    original = tmp_path / "source.db3"
    original.write_bytes(b"test-content-only")
    compressed = tmp_path / "source.db3.zstd"
    subprocess.run(["zstd", str(original), "-o", str(compressed)], check=True, capture_output=True)
    meta = {"rosbag2_bagfile_information": {"compression_mode": "file", "compression_format": "zstd",
             "relative_file_paths": [compressed.name], "files": [{"path": compressed.name}]}}
    metadata = tmp_path / "metadata.yaml"
    metadata.write_text(yaml.safe_dump(meta))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with playback_source(tmp_path) as (private, info):
        assert private != tmp_path
        assert (private / info["relative_file_paths"][0]).read_bytes() == original.read_bytes()
        assert info["compression_mode"] == ""
    assert not private.exists()
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_python310_syntax():
    import ast
    for path in (ROOT / "ros2/omi_sensors/omi_sensors").glob("*.py"):
        ast.parse(path.read_text(), feature_version=(3, 10))


def test_replay_excludes_control_and_disabled_depth(config):
    from omi_sensors.config import replay_topics
    available = ["/tj/dm_sensor/a_raw", "/tj/dm_sensor/a_depth", "/arm/command", "/gripper/command", "/omi/tactile/a/deformation"]
    assert replay_topics(config, available) == ["/omi/tactile/a/deformation", "/tj/dm_sensor/a_raw"]
    config["tactile"]["enabled"] = False
    assert replay_topics(config, available) == []
