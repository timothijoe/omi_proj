"""Compare migrated reconstruction against saved numeric fixtures, without ROS/hardware."""

import argparse
import json
from pathlib import Path
import platform
import sys

import numpy as np

from .reconstruction import FieldProcessor, INPUT_REPRESENTATION, VERSION
from .vendor_bundle import file_hash, verify_bundle, bundle_content_sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sdk-root", "baseline-dir", "fixtures", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--atol", type=float, default=1e-6)
    parser.add_argument("--rtol", type=float, default=1e-5)
    parser.add_argument("--preview-dir", type=Path, help="optional OMI renderer comparison PNGs; requires main project source and Pillow")
    args = parser.parse_args(argv)
    if not all(np.isfinite(v) and v >= 0 for v in (args.atol, args.rtol)):
        parser.error("tolerances must be finite and nonnegative")
    if args.output.exists():
        parser.error("output already exists")
    manifest = verify_bundle(args.sdk_root)
    files = sorted(args.fixtures.glob("[ab]_*.npz"))
    if not files:
        parser.error("no a_*.npz/b_*.npz fixtures")
    if args.preview_dir:
        from PIL import Image, ImageDraw
        from omi_hil_rl.real.tactile_vectors import render_vector_field
        args.preview_dir.mkdir(parents=True, exist_ok=False)
    report = {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
              "processing_version": VERSION, "field_source": "image_reconstruction",
              "input_representation": INPUT_REPRESENTATION, "rtol": args.rtol, "atol": args.atol,
              "sdk_bundle_content_sha256": bundle_content_sha256(manifest),
              "sdk_manifest_sha256": file_hash(args.sdk_root / "migration-manifest.json"), "samples": []}
    with FieldProcessor(args.baseline_dir, args.sdk_root) as processor:
        report.update(baseline_id=processor.baseline_id, sdk_python_sha256=processor.sdk_hash)
        for path in files:
            with np.load(path, allow_pickle=False) as fixture:
                actual = processor.process(path.name[0], fixture["raw"])
                sample = {"fixture": path.name, "fixture_sha256": file_hash(path), "fields": {}}
                tiles = []
                for kind, value in zip(("deformation", "shear"), actual):
                    expected = fixture[kind]
                    if expected.shape != value.shape or not np.isfinite(expected).all():
                        raise ValueError("invalid reference field: " + str(path))
                    error = np.abs(value.astype(np.float64) - expected)
                    sample["fields"][kind] = {"shape": list(value.shape), "dtype": str(value.dtype),
                        "max_abs_error": float(error.max()), "mae": float(error.mean()),
                        "exact": bool(np.array_equal(value, expected)),
                        "passed": bool(np.allclose(value, expected, rtol=args.rtol, atol=args.atol))}
                    if args.preview_dir:
                        for label, array in (("reference", expected), ("migrated", value)):
                            pixels, _ = render_vector_field(array, step=16, scale_px_per_unit=2.0, deadband=0.2, max_arrow_px=24.0)
                            tile = Image.new("RGB", (pixels.shape[1], pixels.shape[0] + 28), (18, 20, 24))
                            tile.paste(Image.fromarray(pixels), (0, 28))
                            ImageDraw.Draw(tile).text((8, 7), path.stem + " " + kind + " " + label, fill="white")
                            tiles.append(tile)
                if tiles:
                    width, height = tiles[0].size
                    sheet = Image.new("RGB", (width * 2, height * 2))
                    for index, tile in enumerate(tiles):
                        sheet.paste(tile, ((index % 2) * width, (index // 2) * height))
                    sheet.save(args.preview_dir / (path.stem + ".png"))
                report["samples"].append(sample)
    report["passed"] = all(f["passed"] for s in report["samples"] for f in s["fields"].values())
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({"passed": report["passed"], "samples": len(files), "report": str(args.output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
