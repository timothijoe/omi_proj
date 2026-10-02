#!/usr/bin/env bash
# Independent SDK-native viewer. No default device startup, no old viewer imports.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
omi_distro="${OMI_ROS_DISTRO:-${ROS_DISTRO:-}}"
if [[ -z "$omi_distro" ]]; then
    source /etc/os-release
    case "$VERSION_ID" in 24.04) omi_distro=jazzy ;; 22.04) omi_distro=humble ;; *) echo 'Set OMI_ROS_DISTRO to humble or jazzy' >&2; exit 2 ;; esac
fi
[[ "$omi_distro" == jazzy || "$omi_distro" == humble ]] || { echo 'Supported ROS: jazzy/humble' >&2; exit 2; }
[[ -f "/opt/ros/$omi_distro/setup.bash" ]] || { echo "Missing ROS $omi_distro" >&2; exit 2; }
source "/opt/ros/$omi_distro/setup.bash"
export PYTHONPATH="$omi_root/ros2/omi_sensors${PYTHONPATH:+:$PYTHONPATH}"
exec "${OMI_SENSOR_PYTHON:-/usr/bin/python3}" -m omi_sensors.dashboard_launcher \
    --config "$omi_root/ros2/omi_sensors/config/sdk_dashboard.example.json" \
    --rviz-config "$omi_root/ros2/omi_sensors/config/sdk_dashboard.rviz" "$@"
