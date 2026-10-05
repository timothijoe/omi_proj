#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/env.sh"
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.training.demo_view "$@"
