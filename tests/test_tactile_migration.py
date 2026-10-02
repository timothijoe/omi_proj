import json
from pathlib import Path
import sys
from types import ModuleType

import numpy as np
import pytest

from omi_sensors.reconstruction import FieldProcessor, validate_field
from omi_sensors.vendor_bundle import import_bundle, verify_bundle


def test_bundle_import_and_tamper_detection(tmp_path):
    source, target = tmp_path / "source", tmp_path / "bundle"
    (source / "dmrobotics").mkdir(parents=True)
    (source / "Daimon").mkdir()
    (source / "dmrobotics/__init__.py").write_text("# fake SDK, never executed")
    (source / "Daimon/runtime.so").write_bytes(b"fake")
    (source / "logs").mkdir()
    (source / "logs/private.txt").write_text("not part of runtime")
    manifest = import_bundle(source, target)
    assert len(manifest["files"]) == 2
    assert not (target / "logs").exists()
    assert verify_bundle(target) == manifest
    with pytest.raises(FileExistsError):
        import_bundle(source, target)
    (target / "Daimon/runtime.so").write_bytes(b"modified")
    with pytest.raises(ValueError, match="differs"):
        verify_bundle(target)


def test_bundle_rejects_symlink(tmp_path):
    (tmp_path / "source/dmrobotics").mkdir(parents=True)
    (tmp_path / "source/Daimon").mkdir()
    (tmp_path / "source/dmrobotics/__init__.py").symlink_to("/etc/os-release")
    with pytest.raises(ValueError, match="symlinks"):
        import_bundle(tmp_path / "source", tmp_path / "bundle")


def test_migrated_processor_contract(tmp_path, monkeypatch):
    sdk, baseline = tmp_path / "sdk", tmp_path / "baseline"
    (sdk / "dmrobotics").mkdir(parents=True)
    baseline.mkdir()
    (baseline / "metadata.json").write_text(json.dumps({"sensor_identity": {}}))
    for side in ("a", "b"):
        np.save(baseline / ("tactile_" + side + "_base.npy"), np.zeros((3, 4), dtype=np.uint8))
    trackers = []

    class Tracker:
        def __init__(self, **kwargs):
            assert kwargs == {"backend": "cpu", "model_path": "standard"}
            self.closed = 0
            trackers.append(self)

        def setBaseFrame(self, base):
            self.base = base

        def t(self, value):
            return np.repeat((value - self.base)[..., None], 2, axis=-1).astype(np.float32)

        def close(self):
            self.closed += 1

    class Decomposer:
        def __init__(self, *args):
            assert args == ((3, 4), (1, 1), "cpu")

        def decompose(self, value):
            return value * 0.5

    module = ModuleType("dmrobotics.src.dmSDK")
    module.FlowTracker, module.Decomposer = Tracker, Decomposer
    parent = ModuleType("dmrobotics")
    parent.__file__ = str(sdk / "dmrobotics/__init__.py")
    monkeypatch.setitem(sys.modules, "dmrobotics", parent)
    monkeypatch.setitem(sys.modules, "dmrobotics.src.dmSDK", module)
    with FieldProcessor(baseline, sdk) as processor:
        d, s = processor.process("a", np.ones((3, 4), dtype=np.uint8))
        np.testing.assert_array_equal(d, 1)
        np.testing.assert_array_equal(s, 0.5)
        with pytest.raises(ValueError, match="mono8 infer"):
            processor.process("a", np.zeros((3, 4, 3), dtype=np.uint8))
    processor.close()
    assert all(t.closed == 1 for t in trackers)


def test_live_viewer_uses_shared_processor():
    from omi_hil_rl.real.tactile_live_migrated import FieldProcessor as ViewerProcessor
    assert ViewerProcessor is FieldProcessor


def test_invalid_field_rejected():
    with pytest.raises(ValueError):
        validate_field(np.full((2, 2, 2), np.nan))
