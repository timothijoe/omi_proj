#!/usr/bin/env bash
# Recorded grid24x16 + wrist ROI + robot. No devices or command replay.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then source "$OMI_MARVIN_MSGS_SETUP"; fi
export OMI_PROJECT_ROOT="$omi_root"
export PYTHONPATH="$omi_root/src:$omi_root/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
exec "${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}" -m omi_hil_rl.real.grid_recorded_review "$@"
