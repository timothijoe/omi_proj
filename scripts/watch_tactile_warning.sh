#!/usr/bin/env bash
# Read-only subscriptions and threshold logs; no robot motion output.
set -eo pipefail
omi_warning_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
export OMI_PROJECT_ROOT="$omi_warning_root"
export PYTHONPATH="$omi_warning_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_DEFAULT_PROFILES_FILE:-$omi_warning_root/ros2/omi_sensors/config/live_dashboard_network.xml}"
exec "${OMI_WARNING_PYTHON:-$omi_warning_root/.venv/bin/python}" -m omi_hil_rl.real.tactile_warning "$@"
