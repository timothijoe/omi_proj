#!/usr/bin/env bash
# Playback only; no robot command topics. Ctrl+C stops all child processes.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 || "${1:-}" == --help ]]; then
    echo "Usage: bash scripts/view_tactile_bag.sh BAG [PLAYBACK_RATE=1.0] [--no-rviz]"
    echo "Optional: OMI_TACTILE_BASELINE, OMI_DAIMON_SDK_ROOT, OMI_TACTILE_PYTHON, OMI_TACTILE_RATE=10"
    exit 0
fi
omi_bag="$1"
omi_rate="${2:-1.0}"
omi_python="${OMI_TACTILE_PYTHON:-$omi_root/local/venvs/daimon312/bin/python}"
omi_baseline="${OMI_TACTILE_BASELINE:-$omi_root/local/tactile/record010_zero_load_25_26_confirmed_v2}"
omi_sdk="${OMI_DAIMON_SDK_ROOT:-$omi_root/../diamond/daimon_stuff/dm_gripper_tac_py}"
[[ -f "$omi_bag/metadata.yaml" ]] || { echo "Missing bag metadata: $omi_bag" >&2; exit 1; }
[[ -x "$omi_python" ]] || { echo "Missing Python: $omi_python" >&2; exit 1; }
[[ -f "$omi_baseline/metadata.json" ]] || { echo "Missing baseline: $omi_baseline" >&2; exit 1; }
[[ -d "$omi_sdk/dmrobotics" ]] || { echo "Missing SDK: $omi_sdk" >&2; exit 1; }
if [[ ! "$omi_rate" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ || "$omi_rate" =~ ^0*([.]0*)?$ ]]; then
    echo "Playback rate must be positive" >&2
    exit 2
fi
if [[ $# -gt 3 || ( $# -eq 3 && "$3" != --no-rviz ) ]]; then
    echo "Unknown arguments; use --help" >&2
    exit 2
fi
source /opt/ros/jazzy/setup.bash
set -u
export PYTHONPATH="$omi_root/src${PYTHONPATH:+:$PYTHONPATH}"
# A dedicated local domain keeps this bag viewer separate from the robot graph.
export ROS_DOMAIN_ID="${OMI_TACTILE_ROS_DOMAIN_ID:-87}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_LOCALHOST_ONLY=1
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
echo "Preparing private raw-only playback cache (source bag stays untouched)..."
omi_cached_bag="$("$omi_python" -m omi_hil_rl.real.tactile_replay_cache "$omi_bag" "$omi_root/local/tactile/replay_cache")"
omi_pids=()
cleanup() {
    trap - EXIT INT TERM
    for omi_pid in "${omi_pids[@]}"; do kill -TERM "$omi_pid" 2>/dev/null || true; done
    for omi_pid in "${omi_pids[@]}"; do wait "$omi_pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$omi_root"
"$omi_python" -m omi_hil_rl.real.tactile_live fields --baseline-dir "$omi_baseline" --sdk-root "$omi_sdk" --rate "${OMI_TACTILE_RATE:-10}" &
omi_pids+=("$!")
"$omi_python" -m omi_hil_rl.real.tactile_live dashboard --rate "${OMI_TACTILE_RATE:-10}" &
omi_pids+=("$!")
if [[ "${3:-}" != --no-rviz ]]; then
    rviz2 -d "$omi_root/scripts/tactile.rviz" &
    omi_pids+=("$!")
fi
ros2 bag play "$omi_cached_bag" --rate "$omi_rate" --loop --delay 5 --disable-keyboard-controls --topics /tj/dm_sensor/a_raw /tj/dm_sensor/b_raw &
omi_pids+=("$!")
echo "Tactile replay on localhost ROS domain $ROS_DOMAIN_ID. Ctrl+C to stop."
wait -n "${omi_pids[@]}"
