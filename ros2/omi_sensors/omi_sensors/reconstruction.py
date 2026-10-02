"""OMI-owned fixed-baseline reconstruction adapter; vendor algorithms stay external.

Migrated from omi_hil_rl.real.tactile_live.FieldProcessor. This module requires
only NumPy until construction and never instantiates Sensor or connects devices.
Input is the validated legacy mono8 infer image, not arbitrary SDK camera raw.
"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

VERSION = "daimon-cpu-fixed-baseline-v1"
INPUT_REPRESENTATION = "legacy_infer_mono8"


def validate_field(value):
    value = np.asarray(value)
    if value.ndim != 3 or value.shape[2] != 2 or min(value.shape[:2]) < 1:
        raise ValueError("expected H x W x 2 field")
    if value.dtype.kind != "f" or not np.isfinite(value).all():
        raise ValueError("expected finite floating point field")
    result = np.asarray(value, dtype=np.float32)
    if not np.isfinite(result).all():
        raise ValueError("field exceeds float32 range")
    return result


class FieldProcessor:
    def __init__(self, baseline_dir, sdk_root):
        baseline_dir, sdk_root = Path(baseline_dir), Path(sdk_root).resolve()
        if not (sdk_root / "dmrobotics").is_dir():
            raise FileNotFoundError("SDK not found: " + str(sdk_root))
        existing = sys.modules.get("dmrobotics")
        if existing is not None and not Path(existing.__file__).resolve().is_relative_to(sdk_root):
            raise RuntimeError("A different SDK is already imported; use a fresh process to compare SDK versions")
        sys.path.insert(0, str(sdk_root))
        from dmrobotics.src.dmSDK import Decomposer, FlowTracker

        self.decomposer_class = Decomposer
        self.trackers, self.decomposers = {}, {}
        metadata_bytes = (baseline_dir / "metadata.json").read_bytes()
        self.identity = json.loads(metadata_bytes).get("sensor_identity", {})
        digest = hashlib.sha256(metadata_bytes)
        bases = {}
        for side in ("a", "b"):
            path = baseline_dir / ("tactile_" + side + "_base.npy")
            digest.update(path.read_bytes())
            base = np.load(path, allow_pickle=False)
            if base.ndim != 2 or base.dtype != np.uint8:
                raise ValueError("baseline must be mono8 H x W")
            bases[side] = base
        self.baseline_id = digest.hexdigest()
        sdk_digest = hashlib.sha256()
        for path in sorted((sdk_root / "dmrobotics").rglob("*.py")):
            sdk_digest.update(str(path.relative_to(sdk_root)).encode())
            sdk_digest.update(path.read_bytes())
        # Retain legacy hash exactly for old metadata comparisons. The migration
        # manifest separately hashes runtime binaries and model assets as well.
        self.sdk_hash = sdk_digest.hexdigest()
        self.shapes = {side: base.shape for side, base in bases.items()}
        try:
            for side, base in bases.items():
                tracker = FlowTracker(backend="cpu", model_path="standard")
                self.trackers[side] = tracker
                tracker.setBaseFrame(base)
        except Exception:
            self.close()
            raise

    def process(self, side, raw):
        if side not in self.shapes or raw.shape != self.shapes[side] or raw.dtype != np.uint8:
            raise ValueError("input side/shape/dtype does not match mono8 infer baseline")
        deformation = validate_field(self.trackers[side].t(raw))
        if side not in self.decomposers:
            self.decomposers[side] = self.decomposer_class(deformation.shape[:2], (1, 1), "cpu")
        shear = validate_field(self.decomposers[side].decompose(deformation))
        if shear.shape != deformation.shape:
            raise ValueError("shear/deformation shapes differ")
        return deformation, shear

    def close(self):
        trackers, self.trackers = self.trackers, {}
        for tracker in trackers.values():
            tracker.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
