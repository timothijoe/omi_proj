"""Create a private raw-only replay bag without decompressing into the source directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .tactile_offline import TOPICS
from .camera_panels import CAMERA_TOPICS


def prepare(bag: Path, cache_root: Path, *, with_cameras: bool = False) -> Path:
    import rosbag2_py
    import yaml

    bag = bag.resolve()
    metadata_bytes = (bag / "metadata.yaml").read_bytes()
    metadata = yaml.safe_load(metadata_bytes)["rosbag2_bagfile_information"]
    files = [(bag / name).resolve() for name in metadata["relative_file_paths"]]
    if any(not path.is_relative_to(bag) for path in files):
        raise ValueError("bag file paths must remain within source directory")
    signature = dict(source=str(bag), metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest(),
                     files=[(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files], version=1)
    wanted = {TOPICS[side]["raw"] for side in ("a", "b")}
    if with_cameras:
        wanted.update(CAMERA_TOPICS.values())
        signature["topics"] = sorted(wanted)
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = cache_root / key
    if destination.exists():
        if not (destination / "provenance.json").is_file():
            raise RuntimeError(f"incomplete cache: {destination}")
        return destination / "bag"
    # The temporary directory belongs to this invocation and is removed on exit.
    with tempfile.TemporaryDirectory(prefix="tactile-", dir=cache_root) as temporary:
        staging = Path(temporary)
        output = staging / "result"
        output.mkdir()
        writer = rosbag2_py.SequentialWriter()
        writer.open(rosbag2_py.StorageOptions(uri=str(output / "bag"), storage_id="mcap"),
                    rosbag2_py.ConverterOptions("cdr", "cdr"))
        created = set()
        counts = {topic: 0 for topic in wanted}
        for index, source in enumerate(files):
            path = source
            if source.suffix == ".zstd":
                path = staging / f"input_{index}.mcap"
                with path.open("xb") as stream:
                    subprocess.run(["zstd", "-d", "-c", str(source)], stdout=stream, check=True)
            elif metadata.get("compression_mode", "").lower() not in ("", "none"):
                raise ValueError("only uncompressed or file-zstd MCAP bags are supported")
            reader = rosbag2_py.SequentialReader()
            reader.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="mcap"),
                        rosbag2_py.ConverterOptions("cdr", "cdr"))
            for topic in reader.get_all_topics_and_types():
                if topic.name in wanted and topic.name not in created:
                    writer.create_topic(topic)
                    created.add(topic.name)
            reader.set_filter(rosbag2_py.StorageFilter(topics=sorted(wanted)))
            while reader.has_next():
                topic, data, stamp = reader.read_next()
                writer.write(topic, data, stamp)
                counts[topic] += 1
            del reader
            if path != source:
                path.unlink()
        del writer
        if not all(counts.values()):
            raise ValueError(f"missing required frames: {counts}")
        (output / "provenance.json").write_text(json.dumps(dict(signature=signature, counts=counts), indent=2))
        # Concurrent builds may finish first; preserve their complete cache.
        if not destination.exists():
            try:
                output.rename(destination)
            except OSError:
                if not (destination / "provenance.json").is_file():
                    raise
    return destination / "bag"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("--with-cameras", action="store_true")
    args = parser.parse_args()
    print(prepare(args.bag, args.cache_root, with_cameras=args.with_cameras).resolve())


if __name__ == "__main__":
    main()
