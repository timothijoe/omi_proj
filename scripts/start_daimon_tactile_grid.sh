#!/usr/bin/env bash
# Independent numeric-only 24(width)x16(height) transport; no legacy viewer.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$omi_root/scripts/start_daimon_live.sh" tactile "$@" --tactile-mode grid24x16
