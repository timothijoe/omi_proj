"""A-arm TCP reach task on the external cooking-project Marvin scene."""

from __future__ import annotations

import os
from pathlib import Path

from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


A_GOAL_RAD = (0.0, -0.25, 0.0, -0.35, 0.0, 0.1, 0.0)
A_JOINT_NAMES = tuple(f"left_joint{i}" for i in range(1, 8))
A_ACTUATOR_NAMES = tuple(f"act_left_joint{i}" for i in range(1, 8))


def scene_path(path: Path | str | None = None) -> Path:
    """Resolve the untracked model without copying third-party assets."""
    candidate = path or os.environ.get("OMI_TIANJI_SCENE")
    if not candidate:
        raise FileNotFoundError(
            "Set OMI_TIANJI_SCENE or pass --scene pointing to "
            "cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml"
        )
    result = Path(candidate).expanduser().resolve()
    if not result.is_file():
        raise FileNotFoundError(f"Tianji MJCF does not exist: {result}")
    return result


class TianjiAReachEnv(TianjiSurrogateEnv):
    """A (left) arm reaches a fixed, FK-derived TCP target in the Marvin scene.

    The scene and its mesh assets are supplied externally. Its parameters are
    useful for simulation but have not been calibrated to the physical robot.
    """

    def __init__(self, *, scene: Path | str | None = None, **kwargs):
        super().__init__(
            model_path=scene_path(scene),
            joint_names=A_JOINT_NAMES,
            actuator_names=A_ACTUATOR_NAMES,
            tcp_site_name="left_palm_tcp_site",
            task="tcp",
            goal_rad=A_GOAL_RAD,
            success_tolerance_m=0.035,
            model_kind="cooking_marvin_dual_arm_scene_A",
            **kwargs,
        )
