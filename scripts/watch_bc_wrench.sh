#!/usr/bin/env bash
# Read-only per-Start BC wrench delta monitor; no robot command publisher.
set -eo pipefail
omi_watch_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
export PYTHONPATH="$omi_watch_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_DEFAULT_PROFILES_FILE:-$omi_watch_root/ros2/omi_sensors/config/live_dashboard_network.xml}"
exec "$omi_watch_root/local/cuda-env/bin/python" -m omi_hil_rl.hil.watch_bc_wrench "$@"
