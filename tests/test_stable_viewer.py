import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stable_viewer_files_match_frozen_checkpoint():
    manifest = json.loads((ROOT / "manifests/stable-observation-viewer.json").read_text())
    for relative, expected in manifest["files"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative


def test_migrated_entry_is_opt_in():
    stable = (ROOT / "scripts/view_observation_bag.sh").read_text()
    migrated = (ROOT / "scripts/view_observation_bag_migrated.sh").read_text()
    assert 'view_tactile_bag.sh' in stable and 'migrated' not in stable
    assert 'view_tactile_bag_migrated.sh' in migrated
    script = (ROOT / "scripts/view_tactile_bag_migrated.sh").read_text()
    assert 'omi_hil_rl.real.tactile_live_migrated fields' in script
    assert 'local/vendor/daimon_tactile' in script
