#!/usr/bin/env bash
# Record every inferred input window; preview unless --execute is explicitly supplied.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$omi_root/scripts/run_wrench_policy_gamepad.sh" --record-observations "$@"
