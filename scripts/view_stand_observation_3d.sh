#!/usr/bin/env bash
# Separate visual-only Stand model review; stable old launcher is unchanged.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 2 || "${1:-}" == --help ]]; then
    echo 'Usage: bash scripts/view_stand_observation_3d.sh ZIP_OR_BAG MODEL.rar [RATE=1] [--no-rviz]'
    echo 'localhost domain98; unverified base/joint mapping; no controller or TCP claim.'
    exit 0
fi
omi_rate="${3:-1}"
if [[ $# -gt 4 || ( $# -eq 4 && "$4" != --no-rviz ) || ! "$omi_rate" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ || "$omi_rate" =~ ^0*([.]0*)?$ ]]; then
    echo 'Invalid arguments; use --help' >&2; exit 2
fi
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then source "$OMI_MARVIN_MSGS_SETUP"; fi
omi_python="${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=98 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
omi_model_args=()
if [[ "${OMI_STAND_AXIS_CORRECTED:-0}" == 1 ]]; then
    export ROS_DOMAIN_ID=94
    omi_model_args+=(--corrected)
fi
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
omi_rsp="$(ros2 pkg prefix robot_state_publisher)/lib/robot_state_publisher/robot_state_publisher"
omi_cache="$("$omi_python" -m omi_hil_rl.real.recorded_observation prepare "$1" "$omi_root/local/recorded_review")"
omi_model="$("$omi_python" -m omi_hil_rl.real.stand_urdf_review prepare "$2" "$omi_root/local/robot_state/stand_models" "$omi_root/scripts/recorded_observation_3d.rviz" "${omi_model_args[@]}")"
echo "Stand review model: $omi_model"
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
"$omi_python" -m omi_hil_rl.real.recorded_observation view "$omi_cache" --rate "$omi_rate" &
omi_pids+=("$!")
"$omi_python" -m omi_hil_rl.real.stand_urdf_review markers "${omi_model_args[@]}" &
omi_pids+=("$!")
if [[ "${4:-}" != --no-rviz ]]; then
    rviz2 -d "$omi_model/review.rviz" --ros-args \
        -r /tf:=/omi/replay_3d/tf -r /tf_static:=/omi/replay_3d/tf_static &
    omi_pids+=("$!")
fi
echo "Read-only Stand review on domain$ROS_DOMAIN_ID; Ctrl+C or close RViz to stop."
wait -n "${omi_pids[@]}"
