#!/usr/bin/env bash
# Opt-in robot text panel. Original viewer and its sensor-only playback stay intact.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 || "${1:-}" == --help ]]; then
    echo "Usage: bash scripts/view_observation_robot_bag.sh BAG [RATE=1.0] [--no-rviz]"
    echo "Reads local/robot_state/viewer.env automatically; see scripts/robot_viewer.env.example."
    echo "Uses original viewer settings; no robot command topics are replayed."
    exit 0
fi
if [[ $# -gt 3 || ( $# -eq 3 && "$3" != --no-rviz ) ]]; then
    echo "Invalid arguments; use --help" >&2; exit 2
fi
omi_rate="${2:-1.0}"
if [[ ! "$omi_rate" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ || "$omi_rate" =~ ^0*([.]0*)?$ ]]; then
    echo "Playback rate must be positive" >&2; exit 2
fi
source "$omi_root/scripts/robot_viewer_env.sh" "$omi_root"
source /opt/ros/jazzy/setup.bash
if [[ -n "${OMI_MARVIN_MSGS_SETUP:-}" ]]; then
    [[ -f "$OMI_MARVIN_MSGS_SETUP" ]] || { echo "Missing message overlay: $OMI_MARVIN_MSGS_SETUP; edit local/robot_state/viewer.env" >&2; exit 1; }
    source "$OMI_MARVIN_MSGS_SETUP"
fi
omi_python="${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}"
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID="${OMI_TACTILE_ROS_DOMAIN_ID:-87}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_LOCALHOST_ONLY=1
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
[[ -x "$omi_python" ]] || { echo "Missing Python: $omi_python" >&2; exit 1; }
[[ -d "$OMI_DAIMON_SDK_ROOT/dmrobotics" ]] || { echo "Missing SDK: $OMI_DAIMON_SDK_ROOT; edit local/robot_state/viewer.env" >&2; exit 1; }
"$omi_python" -c 'from marvin_msgs.msg import Jointfeedback, JointcmdArm' || {
    echo "Cannot load marvin_msgs. Configure its matching Jazzy overlay in local/robot_state/viewer.env." >&2
    exit 1
}
echo "Preparing read-only robot timeline; first run may need temporary decompression space..."
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
"$omi_python" -m omi_hil_rl.real.robot_state_panel view "$omi_timeline" &
omi_pids+=("$!")
bash "$omi_root/scripts/view_observation_bag.sh" "$1" "$omi_rate" --no-rviz &
omi_pids+=("$!")
if [[ "${3:-}" != --no-rviz ]]; then
    rviz2 -d "$omi_root/scripts/observation_robot.rviz" &
    omi_pids+=("$!")
fi
echo "Robot state compositor on localhost domain $ROS_DOMAIN_ID. Ctrl+C stops all children."
wait -n "${omi_pids[@]}"
