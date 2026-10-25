#!/usr/bin/env bash
# Independent read-only panels. The original v1 launcher is unchanged.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
omi_live_setup="${OMI_LIVE_MARVIN_MSGS_SETUP:-$omi_root/local/live_feedback_ws/install/local_setup.bash}"
if [[ -f "$omi_live_setup" ]]; then
    source "$omi_live_setup"
fi
export OMI_PROJECT_ROOT="$omi_root"
export PYTHONPATH="$omi_root/src:$omi_root/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
exec "${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}" -m omi_hil_rl.real.grid_live_v2 "$@"
