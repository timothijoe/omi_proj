#!/usr/bin/env bash
# Preview by default; only explicit --execute enables the final robot publisher.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/jazzy/setup.bash
export OMI_PROJECT_ROOT="$omi_root"
export PYTHONPATH="$omi_root/src:$omi_root/ros2/omi_sensors:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${OMI_POLICY_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export FASTRTPS_DEFAULT_PROFILES_FILE="$omi_root/ros2/omi_sensors/config/live_dashboard_network.xml"
export CUBLAS_WORKSPACE_CONFIG=:4096:8
exec "${OMI_POLICY_PYTHON:-$omi_root/local/cuda-env/bin/python}" -m omi_hil_rl.real.policy_gamepad "$@"
