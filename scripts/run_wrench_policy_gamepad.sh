#!/usr/bin/env bash
# New passive wrench BC model; preview unless the caller explicitly adds --execute.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$omi_root/scripts/run_policy_gamepad.sh" \
  --checkpoint "$omi_root/local/passive_bc_20261005_wrench_train_v1/actor.pt" \
  --model-kind passive-wrench-bc --eef-reference raw \
  --policy-scale 1.0 --speed-mm-s 5 --rotation-deg-s 5 \
  --candidate-expiry off --home-button-code 307 "$@"
