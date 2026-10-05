#!/usr/bin/env bash
set -eo pipefail
omi_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$omi_root/scripts/env_ros.sh"
exec "$omi_root/.venv/bin/python" -m omi_hil_rl.hil.demo_bag "$@"
