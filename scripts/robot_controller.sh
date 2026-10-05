#!/usr/bin/env bash
# Build or inspect the migrated receiver without connecting to a robot.
set -eo pipefail
controller_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
controller_ws="$controller_root/local/ros2/robot_controller_ws"
controller_action="${1:---help}"
case "$controller_action" in
  --help|-h)
    echo 'Usage: bash scripts/robot_controller.sh {build|preview}'
    echo 'build: build matching live messages and receiver in local/ros2/robot_controller_ws'
    echo 'preview: isolated, disconnected ROS node; no SDK import or device connection'
    exit 0 ;;
  build|preview) ;;
  *) echo "Unknown action: $controller_action" >&2; exit 2 ;;
esac
if [[ $# -ne 1 ]]; then
  echo 'No extra arguments accepted; see tutorials/robot_controller.md' >&2
  exit 2
fi
source "/opt/ros/${OMI_ROS_DISTRO:-jazzy}/setup.bash"
case "$controller_action" in
  build)
    mkdir -p "$controller_ws"
    cd "$controller_ws"
    /usr/bin/python3 -m colcon --log-base "$controller_ws/log" build \
      --base-paths "$controller_root/ros2/arm_delta_cmd" \
                   "$controller_root/ros2/live_feedback_interfaces/marvin_msgs" \
      --build-base "$controller_ws/build" --install-base "$controller_ws/install" \
      --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
    ;;
  preview)
    source "$controller_ws/install/local_setup.bash"
    export ROS_DOMAIN_ID=114 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
    export ARM_SDK_DIR="$controller_root/local/vendor/optical_module_pu/source/OpticalModule_PU/Arm_control"
    exec /usr/bin/python3 -m arm_delta_cmd.delta_ctrl_node --ros-args \
      -p connect_on_start:=false -p motion_authorized:=false \
      -p delta_topic:=/omi/controller_preview/decision \
      -p manual_delta_topic:=/omi/controller_preview/manual_decision \
      -p enable_publish_joint_state:=false -p eef_publish_rate:=0.0 \
      -p publish_root_tf:=none
    ;;
esac
