#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_root"
export PYTHONPATH="$omi_root/src"
exec "$omi_root/local/cuda-env/bin/python" -m omi_hil_rl.hil.behavior_cloning "$@"
