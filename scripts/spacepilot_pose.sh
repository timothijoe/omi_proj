#!/usr/bin/env bash
set -euo pipefail
SPACEPILOT_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$SPACEPILOT_PROJECT_ROOT"
export PYTHONPATH="$SPACEPILOT_PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${OMI_SPACEPILOT_PYTHON:-/usr/bin/python3}" -m omi_hil_rl.hardware.spacepilot_pose "$@"
