#!/usr/bin/env bash
# Independent sensor workspace: deliberately do not activate the RL virtualenv.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /etc/os-release
[[ "$ID" == ubuntu ]] || { echo 'Ubuntu is required by this installer.' >&2; exit 2; }
case "$VERSION_ID" in
  24.04) omi_distro=jazzy ;;
  22.04) omi_distro=humble ;;
  *) echo 'Supported hosts: Ubuntu 24.04/Jazzy or 22.04/Humble' >&2; exit 2 ;;
esac
if [[ -n "${ROS_DISTRO:-}" && "$ROS_DISTRO" != "$omi_distro" ]]; then
    echo "Open a clean shell; expected $omi_distro, found $ROS_DISTRO" >&2; exit 2
fi
omi_packages=(python3-colcon-common-extensions python3-numpy python3-yaml python3-pil python3-pytest zstd
  "ros-$omi_distro-ros-base" "ros-$omi_distro-rosbag2" "ros-$omi_distro-rosbag2-storage-default-plugins"
  "ros-$omi_distro-rosbag2-storage-mcap" "ros-$omi_distro-realsense2-camera" "ros-$omi_distro-rviz2")
if [[ "${1:-}" == --install-system ]]; then
    sudo apt-get update
    sudo apt-get install "${omi_packages[@]}"
elif [[ $# -gt 0 ]]; then
    echo 'Usage: bash scripts/setup_sensors.sh [--install-system]' >&2; exit 2
fi
if [[ ! -f "/opt/ros/$omi_distro/setup.bash" ]]; then
    echo "Install ROS $omi_distro from official ROS documentation first (including apt repository)." >&2
    exit 1
fi
source "/opt/ros/$omi_distro/setup.bash"
if [[ -n "${VIRTUAL_ENV:-}" || -n "${CONDA_PREFIX:-}" ]]; then
    echo 'Deactivate venv/conda first: ROS must use its matching system Python.' >&2; exit 2
fi
mkdir -p "$omi_root/local/sensors_ws"
cd "$omi_root/local/sensors_ws"
/usr/bin/colcon build --base-paths "$omi_root/ros2/omi_sensors" --packages-select omi_sensors
echo "Built sensor package. Source: $omi_root/local/sensors_ws/install/setup.bash"
echo "Copy ros2/omi_sensors/config/sensors.example.json to local/sensors.json and configure your devices."
echo "Check: ros2 run omi_sensors omi-sensors --config $omi_root/local/sensors.json doctor"
