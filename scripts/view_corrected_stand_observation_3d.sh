#!/usr/bin/env bash
# New Stand geometry, joint directions matched to legacy replay convention.
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 2 || "${1:-}" == --help ]]; then
    echo 'Usage: bash scripts/view_corrected_stand_observation_3d.sh ZIP_OR_BAG MODEL.rar [RATE=1] [--no-rviz]'
    echo 'localhost domain94; corrected joint directions; root/TCP/limits NOT calibrated.'
    exit 0
fi
OMI_STAND_AXIS_CORRECTED=1 exec bash "$omi_root/scripts/view_stand_observation_3d.sh" "$@"
