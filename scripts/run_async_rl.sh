#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_root"
source "$omi_root/scripts/env_ros.sh"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
# The actor owns LB+305 save / LB+304 follow and the existing output publishers.
# --tag-follow-calibration selects X/Z; --no-tag-follow disables these controls.
exec "$omi_root/local/cuda-env/bin/python" -m omi_hil_rl.hil.async_training "$@"
