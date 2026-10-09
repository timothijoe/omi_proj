#!/usr/bin/env bash
# Local read-only dashboard; does not start Actor, Learner, ROS or robot services.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_root"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.hil.training_monitor "$@"
