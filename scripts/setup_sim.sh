#!/usr/bin/env bash
set -euo pipefail
unset PYTHONPATH
omi_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PIP_CACHE_DIR="$omi_project_root/local/pip-cache"
omi_python="${OMI_PYTHON:-python3.12}"
"$omi_python" -m venv "$omi_project_root/.venv"
"$omi_project_root/.venv/bin/python" -m pip install \
    --cache-dir "$omi_project_root/local/pip-cache" \
    -r "$omi_project_root/requirements/simulation.lock.txt"
"$omi_project_root/.venv/bin/python" -m pip install \
    --cache-dir "$omi_project_root/local/pip-cache" \
    --no-deps -e "$omi_project_root[dev,train,viz]"
"$omi_project_root/.venv/bin/python" -m pip check
printf 'Environment installed. Activate with: source %s/scripts/env.sh\n' "$omi_project_root"
