#!/usr/bin/env bash
# ROS action experiment, localhost by default; never launches hardware drivers.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$omi_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${OMI_ACTION_TEST_DOMAIN_ID:-${ROS_DOMAIN_ID:-96}}"
case "${OMI_ACTION_TEST_NETWORK:-0}" in
    0) export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ;;
    1) export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET ;;
    *) echo 'OMI_ACTION_TEST_NETWORK must be 0 (localhost) or 1 (subnet)' >&2; exit 2 ;;
esac
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.real.eef_action_bag "$@"
