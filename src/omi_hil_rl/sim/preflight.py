"""Check the external Marvin MJCF and A-arm reach setup before experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from omi_hil_rl.sim.tianji_a_reach import A_ACTUATOR_NAMES, A_JOINT_NAMES, TianjiAReachEnv


def preflight(scene: Path) -> dict:
    env = TianjiAReachEnv(scene=scene)
    try:
        observation, info = env.reset(seed=0)
        return {
            "model_kind": info["model_kind"],
            "arm": "A",
            "scene": str(scene.resolve()),
            "joints": list(A_JOINT_NAMES),
            "actuators": list(A_ACTUATOR_NAMES),
            "tcp_site": "left_palm_tcp_site",
            "joint_limits_rad": env.joint_limits.tolist(),
            "initial_tcp_m": observation["tcp_pos"].tolist(),
            "target_tcp_m": observation["target_tcp_pos"].tolist(),
            "initial_error_m": float(np.linalg.norm(observation["tcp_pos"] - observation["target_tcp_pos"])),
            "success_tolerance_m": env.success_tolerance_m,
            "control_period_s": env.physics_ticks * env.model.opt.timestep,
            "max_joint_delta_rad": env.max_delta_rad,
            "note": "MJCF limits and dynamics are simulation parameters; verify physical hardware separately",
        }
    finally:
        env.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = preflight(args.scene)
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
