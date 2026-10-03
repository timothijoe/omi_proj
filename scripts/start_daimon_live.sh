#!/usr/bin/env bash
# Real tactile + wrist camera, with optional RViz; never record or control motion.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
export PYTHONPATH="$omi_root/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
export OMI_PROJECT_ROOT="$omi_root"
cd "$omi_root"
exec "${OMI_SENSOR_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}" -m omi_sensors.live_launcher "$@"
