# Source from Bash for ROS CLI use; no Python venv or ROS domain changes.
# An explicit OMI_MARVIN_MSGS_SETUP overrides the project-local message package.
omi_marvin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
omi_marvin_ros_setup="/opt/ros/${OMI_ROS_DISTRO:-jazzy}/setup.bash"
omi_marvin_setup="${OMI_MARVIN_MSGS_SETUP:-$omi_marvin_root/local/ros2/marvin_msgs_ws/install/local_setup.bash}"
if [[ ! -f "$omi_marvin_ros_setup" || ! -f "$omi_marvin_setup" ]]; then
    printf 'Missing ROS/message setup: %s or %s\nSee tutorials/marvin_messages.md\n' "$omi_marvin_ros_setup" "$omi_marvin_setup" >&2
    unset omi_marvin_root omi_marvin_ros_setup omi_marvin_setup
    return 1
fi
source "$omi_marvin_ros_setup" || return 1
source "$omi_marvin_setup" || return 1
export OMI_MARVIN_MSGS_SETUP="$omi_marvin_setup"
unset omi_marvin_root omi_marvin_ros_setup omi_marvin_setup
