#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/env_ros.sh"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.hil.collect_episodes "$@"
