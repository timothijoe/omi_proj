# Source this file from Bash: source scripts/env.sh
# Paths are resolved from this file, so activation also works outside the repo.
omi_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$omi_project_root/.venv/bin/activate" ]]; then
    printf 'Missing virtual environment. Run: bash %s/scripts/setup_sim.sh\n' "$omi_project_root" >&2
    unset omi_project_root
    return 1
fi
source "$omi_project_root/.venv/bin/activate"
# The desktop shell may source ROS globally. Keep this environment isolated.
unset PYTHONPATH
export PIP_CACHE_DIR="$omi_project_root/local/pip-cache"
export OMI_TIANJI_SCENE="${OMI_TIANJI_SCENE:-$omi_project_root/local/assets/robot_assets/mujoco/right_chopping_scene.xml}"
# TianjiConfig.sdk_root needs the directory containing SDK_PYTHON.
export OMI_TIANJI_SDK_ROOT="${OMI_TIANJI_SDK_ROOT:-$omi_project_root/../TJ_FX_ROBOT_CONTRL_SDK}"
export MUJOCO_GL="${MUJOCO_GL:-egl}"
unset omi_project_root
