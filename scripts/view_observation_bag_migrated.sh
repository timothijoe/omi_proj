#!/usr/bin/env bash
# Opt-in migrated reconstruction; the original stable viewer is unchanged.
set -eo pipefail
omi_scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export OMI_TACTILE_WITH_CAMERAS=1
exec bash "$omi_scripts/view_tactile_bag_migrated.sh" "$@"
