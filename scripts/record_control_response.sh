#!/usr/bin/env bash
# Passive recorder only; no controller launch, mode changes, SDK or action publisher.
set -eo pipefail
response_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "/opt/ros/${OMI_ROS_DISTRO:-jazzy}/setup.bash"
source "$response_root/local/ros2/robot_controller_ws/install/local_setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
exec /usr/bin/python3 "$response_root/scripts/record_control_response.py" "$@"
