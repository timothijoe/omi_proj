#!/usr/bin/env bash
# Full recorded trajectory, original timing; these are dataset envelope checks,
# not validated robot safety limits. Live sending still requires console confirmation.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
exec /usr/bin/python3 "$SCRIPT_DIR/replay_eef_pose.py" send \
  "$PROJECT_DIR/local/eef_replay/oct04_right_bag002" \
  --log "$PROJECT_DIR/local/eef_replay/right_full_run1.jsonl" \
  --max-step-mm 36 --max-step-deg 4.3 \
  --confirm-controller-contract "$@"
