#!/usr/bin/env bash
# CPU BC/export/shadow tools. Never starts a hardware driver or controller.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -eq 0 || "$1" == --help ]]; then
    echo 'Usage: bash scripts/bag_bc.sh {export|train|shadow} [arguments; --help]'
    echo 'Default localhost domain99; no real control output. See tutorials/bag_bc_shadow.md.'
    exit 0
fi
omi_mode="$1"
shift
case "$omi_mode" in
    export) omi_module=bag_bc_data ;;
    train) omi_module=bc_policy ;;
    shadow) omi_module=bc_shadow ;;
    *) echo 'Expected export, train, shadow' >&2; exit 2 ;;
esac
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then source "$OMI_MARVIN_MSGS_SETUP"; fi
export PYTHONPATH="$omi_root/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${OMI_BC_DOMAIN_ID:-99}"
export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
exec "${OMI_BC_PYTHON:-$omi_root/.venv/bin/python}" -m "omi_hil_rl.training.$omi_module" "$@"
