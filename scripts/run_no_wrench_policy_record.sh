#!/usr/bin/env bash
# Retrained policy without six-axis wrench; retain other tactile grids and recording.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$omi_root/scripts/run_wrench_policy_record.sh" \
  --checkpoint "$omi_root/local/passive_bc_20261005_no_wrench_no_third_train_v1/actor_train_best.pt" "$@"
