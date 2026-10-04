#!/usr/bin/env bash
set -euo pipefail
omi_keypoint_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Uses the isolated system NumPy/Pillow/OpenCV stack; no ROS or policy environment.
exec env -u PYTHONPATH PYTHONPATH="$omi_keypoint_root/src" /usr/bin/python3 -m omi_hil_rl.keypoints.app "$@"
