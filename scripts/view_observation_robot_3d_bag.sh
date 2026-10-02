#!/usr/bin/env bash
# Display-only 3D replay. No robot controller or command replay.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 || "${1:-}" == --help ]]; then
    echo "Usage: bash scripts/view_observation_robot_3d_bag.sh BAG [RATE=1.0] [--no-rviz]"
    echo "Auto local viewer config; project-local arm meshes; default localhost domain96."
    echo "14-joint approximate arm visualization, NOT calibrated gripper/TCP."
    exit 0
fi
omi_rate="${2:-1.0}"
if [[ $# -gt 3 || ( $# -eq 3 && "$3" != --no-rviz ) || ! "$omi_rate" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ || "$omi_rate" =~ ^0*([.]0*)?$ ]]; then
    echo "Invalid arguments; use --help" >&2; exit 2
fi
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then
    source "$OMI_MARVIN_MSGS_SETUP"
fi
omi_python="${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}"
omi_scene="${OMI_REPLAY_ARM_SCENE:-$omi_root/local/assets/robot_assets/mujoco/right_chopping_scene.xml}"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
export OMI_TACTILE_ROS_DOMAIN_ID="${OMI_TACTILE_ROS_DOMAIN_ID:-96}"
export ROS_DOMAIN_ID="$OMI_TACTILE_ROS_DOMAIN_ID"
export ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
omi_rsp="$(ros2 pkg prefix robot_state_publisher)/lib/robot_state_publisher/robot_state_publisher"
[[ -x "$omi_rsp" ]] || { echo "Install ros-jazzy-robot-state-publisher" >&2; exit 1; }
"$omi_python" -c 'from marvin_msgs.msg import Jointfeedback, JointcmdArm' || {
    echo "Configure matching Marvin overlay in local/robot_state/viewer.env" >&2; exit 1;
}
omi_model="$("$omi_python" -m omi_hil_rl.real.robot_replay_3d prepare "$omi_scene" "$omi_root/local/robot_state/models")"
omi_timeline="$("$omi_python" -m omi_hil_rl.real.robot_state_panel prepare "$1" "$omi_root/local/robot_state/replay_cache")"
omi_pids=()
cleanup() {
    trap - EXIT INT TERM
    for omi_pid in "${omi_pids[@]}"; do kill -TERM "$omi_pid" 2>/dev/null || true; done
    for omi_pid in "${omi_pids[@]}"; do wait "$omi_pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$omi_rsp" --ros-args --params-file "$omi_model/publisher.yaml" -r __ns:=/omi/replay_3d \
    -r /tf:=/omi/replay_3d/tf -r /tf_static:=/omi/replay_3d/tf_static &
omi_pids+=("$!")
"$omi_python" -m omi_hil_rl.real.robot_replay_3d view "$omi_timeline" "$omi_model/model.json" &
omi_pids+=("$!")
bash "$omi_root/scripts/view_observation_robot_bag.sh" "$1" "$omi_rate" --no-rviz &
omi_pids+=("$!")
if [[ "${3:-}" != --no-rviz ]]; then
    rviz2 -d "$omi_root/scripts/observation_robot_3d.rviz" --ros-args \
        -r /tf:=/omi/replay_3d/tf -r /tf_static:=/omi/replay_3d/tf_static &
    omi_pids+=("$!")
fi
echo "3D display-only replay on localhost domain $ROS_DOMAIN_ID. Ctrl+C to stop."
wait -n "${omi_pids[@]}"
