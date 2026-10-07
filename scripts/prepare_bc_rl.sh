#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec local/cuda-env/bin/python -m omi_hil_rl.hil.prepare_bc_rl "$@"
