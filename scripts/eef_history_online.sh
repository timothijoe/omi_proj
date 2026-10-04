#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then source "$OMI_MARVIN_MSGS_SETUP"; fi
export PYTHONPATH="$omi_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
# Explicit namespace selection; default test traffic is confined to this host.
export ROS_DOMAIN_ID="${OMI_HISTORY_DOMAIN_ID:-97}"
export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
exec "${OMI_BC_PYTHON:-$omi_root/.venv/bin/python}" -m omi_hil_rl.training.eef_history_node "$@"
