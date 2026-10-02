"""Local SDK import/verification. Does not install, import, patch or execute SDK code."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("SDK bundle must not contain symlinks: " + str(path))
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_file() and path != root / "migration-manifest.json":
            result[str(path.relative_to(root))] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
    return result


def bundle_content_sha256(manifest):
    """Location-independent identity; unlike manifest hash, excludes source path/host."""
    return hashlib.sha256(json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def import_bundle(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not (source / "dmrobotics" / "__init__.py").is_file() or not (source / "Daimon").is_dir():
        raise ValueError("expected SDK containing dmrobotics/ and Daimon/ runtime")
    if target.is_relative_to(source):
        raise ValueError("target must not be inside source SDK")
    names = ["dmrobotics", "Daimon"]
    names += [p.name for p in source.iterdir() if p.is_file() and
              (p.name in ("setup.py", "MANIFEST.in", "README.md", "requirements-gpu.txt", "environment-gpu.yml")
               or p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")))]
    for name in names:
        path = source / name
        if path.is_symlink() or (path.is_dir() and any(p.is_symlink() for p in path.rglob("*"))):
            raise ValueError("SDK contains symlinks; review before importing")
    target.mkdir(parents=True, exist_ok=False)
    # Partial imports are left for inspection on error and never treated as valid
    # without the manifest. Re-run into a new directory, never overwrite.
    for name in names:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(path, target / name)
    files = inventory(target)
    for relative, entry in files.items():
        if file_hash(source / relative) != entry["sha256"]:
            raise ValueError("source changed or copy differs: " + relative)
    manifest = {"schema_version": 1, "source_path_at_import": str(source),
                "import_host_python": platform.python_version(), "import_host_machine": platform.machine(),
                "license_status": "redistribution_not_verified; local use only; preserve vendor notices",
                "algorithm_owner": "Daimon vendor; encrypted implementation unchanged",
                "excluded": [".git", "build", "logs", "demos", "egg-info", "__pycache__"],
                "files": files}
    (target / "migration-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def verify_bundle(target):
    target = Path(target).resolve()
    manifest = json.loads((target / "migration-manifest.json").read_text())
    actual = inventory(target)
    expected = manifest["files"]
    differences = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
    if differences:
        raise ValueError("SDK bundle differs from manifest: " + ", ".join(differences[:20]))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("source", type=Path)
    imp.add_argument("target", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = import_bundle(args.source, args.target) if args.command == "import" else verify_bundle(args.target)
        print(json.dumps({"target": str(args.target.resolve()), "files": len(manifest["files"]), "verified": True}))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
