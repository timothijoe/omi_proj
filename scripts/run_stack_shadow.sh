#!/usr/bin/env bash
# File-only inference audit; no robot commands or action publishers.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$omi_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${OMI_SHADOW_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export FASTRTPS_DEFAULT_PROFILES_FILE="$omi_root/ros2/omi_sensors/config/live_dashboard_network.xml"
export CUBLAS_WORKSPACE_CONFIG=:4096:8
exec "${OMI_SHADOW_PYTHON:-$omi_root/local/cuda-env/bin/python}" -m omi_hil_rl.training.stack_shadow "$@"
