#!/usr/bin/env bash
# Opt-in same-host large-image transport; original launcher default is unchanged.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$omi_root/scripts/start_daimon_live.sh" "$@" --transport local-shm
