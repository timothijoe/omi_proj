#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$omi_root"
source "$omi_root/scripts/env_ros.sh"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
exec "$omi_root/local/cuda-env/bin/python" -m omi_hil_rl.hil.bc_rollout "$@"
