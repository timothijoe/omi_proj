#!/usr/bin/env bash
# Wrist RGB + native tactile fields + named OMI corrected Stand, read-only.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 || "${1:-}" == --help ]]; then
    echo 'Usage: bash scripts/view_wrist_observation_3d.sh ZIP_OR_BAG [RATE=1] [--no-rviz]'
    echo 'localhost domain93; named corrected model in local/models; legacy wrist ROI + Lanczos 128.'
    exit 0
fi
omi_rate="${2:-1}"
if [[ $# -gt 3 || ( $# -eq 3 && "$3" != --no-rviz ) || ! "$omi_rate" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ || "$omi_rate" =~ ^0*([.]0*)?$ ]]; then
    echo 'Invalid arguments; use --help' >&2; exit 2
fi
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "$OMI_MARVIN_MSGS_SETUP" ]]; then source "$OMI_MARVIN_MSGS_SETUP"; fi
omi_python="${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
omi_rsp="$(ros2 pkg prefix robot_state_publisher)/lib/robot_state_publisher/robot_state_publisher"
omi_bundle="${OMI_WRIST_MODEL_BUNDLE:-$omi_root/local/models/omi_marvin_stand_axis_corrected_v1}"
omi_model="$("$omi_python" -m omi_hil_rl.real.wrist_recorded_review model "$omi_bundle" "$omi_root/local/robot_state/wrist_models" "$omi_root/scripts/recorded_observation_3d.rviz")"
echo 'Preparing wrist/native-field images (first run may take a minute)...'
omi_cache="$("$omi_python" -m omi_hil_rl.real.wrist_recorded_review prepare "$1" "$omi_root/local/wrist_recorded_review")"
echo "Wrist cache: $omi_cache"
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
"$omi_python" -m omi_hil_rl.real.stand_urdf_review markers --corrected &
omi_pids+=("$!")
if [[ "${3:-}" != --no-rviz ]]; then
    rviz2 -d "$omi_model/review.rviz" --ros-args \
        -r /tf:=/omi/replay_3d/tf -r /tf_static:=/omi/replay_3d/tf_static &
    omi_pids+=("$!")
fi
echo 'Wrist review domain93; Ctrl+C or close RViz to stop. NO CONTROL.'
wait -n "${omi_pids[@]}"
