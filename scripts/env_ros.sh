# Source this file after creating the project virtual environment.
# Optional: export OMI_MARVIN_MSGS_SETUP=/path/to/marvin_msgs/install/setup.bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/env.sh"

omi_ros_distro="${OMI_ROS_DISTRO:-jazzy}"
omi_ros_setup="/opt/ros/$omi_ros_distro/setup.bash"
if [[ ! -f "$omi_ros_setup" ]]; then
    printf 'Missing ROS setup: %s\n' "$omi_ros_setup" >&2
    unset omi_ros_distro omi_ros_setup
    return 1
fi
source "$omi_ros_setup"

if [[ -n "${OMI_MARVIN_MSGS_SETUP:-}" ]]; then
    if [[ ! -f "$OMI_MARVIN_MSGS_SETUP" ]]; then
        printf 'Missing marvin_msgs setup: %s\n' "$OMI_MARVIN_MSGS_SETUP" >&2
        unset omi_ros_distro omi_ros_setup
        return 1
    fi
    source "$OMI_MARVIN_MSGS_SETUP"
fi

# Ubuntu's ROS Python packages use the distribution PyYAML. Keep it visible to
# the project venv unless PyYAML was installed through the `ros` extra.
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
omi_sensor_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../ros2/omi_sensors" && pwd)"
export PYTHONPATH="$omi_sensor_source:$PYTHONPATH"
unset omi_sensor_source
unset omi_ros_distro omi_ros_setup
