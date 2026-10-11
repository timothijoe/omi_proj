#!/usr/bin/env bash
# Archive, restore, or rebuild a disposable replay cache; never starts hardware.
set -euo pipefail
omi_archive_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_archive_root"
export PYTHONPATH="$omi_archive_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$omi_archive_root/local/cuda-env/bin/python" -m omi_hil_rl.hil.run_archive "$@"
