#!/usr/bin/env bash
# Subscribe and record existing wrench streams; never connect SDK or send actions.
set -eo pipefail
omi_wrench_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
export PYTHONPATH="$omi_wrench_root/src:$omi_wrench_root/ros2/omi_sensors:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_DEFAULT_PROFILES_FILE:-$omi_wrench_root/ros2/omi_sensors/config/live_dashboard_network.xml}"
exec "${OMI_WRENCH_PYTHON:-$omi_wrench_root/.venv/bin/python}" -m omi_hil_rl.real.wrench_live "$@"
