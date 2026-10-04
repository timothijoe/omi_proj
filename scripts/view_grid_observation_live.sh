#!/usr/bin/env bash
# Live network subscriptions only; no rosbag player, SDK sessions or control commands.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
omi_live_setup="${OMI_LIVE_MARVIN_MSGS_SETUP:-$omi_root/local/live_feedback_ws/install/local_setup.bash}"
if [[ ! -f "$omi_live_setup" ]]; then
    echo "Missing live feedback interfaces: $omi_live_setup. See tutorials/grid_live_review.md"
    exit 1
fi
source "$omi_live_setup"
export OMI_PROJECT_ROOT="$omi_root"
export PYTHONPATH="$omi_root/src:$omi_root/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
exec "${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}" -m omi_hil_rl.real.grid_live_review "$@"
