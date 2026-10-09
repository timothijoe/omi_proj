#!/usr/bin/env bash
# Read-only browser review of saved periodic RL episodes; no ROS or robot output.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_root"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.hil.periodic_review "$@"
