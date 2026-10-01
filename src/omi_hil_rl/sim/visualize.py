"""Render an A-arm MuJoCo reach episode and its TCP error trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import mujoco
import numpy as np
from PIL import Image, ImageDraw

from omi_hil_rl.sim.intervention import joint_goal_teacher
from omi_hil_rl.sim.tianji_a_reach import TianjiAReachEnv


def render_frame(renderer: mujoco.Renderer, env: TianjiAReachEnv) -> Image.Image:
    camera = mujoco.MjvCamera()
    camera.lookat[:] = (0.0, 0.45, 0.65)
    camera.distance = 2.1
    camera.azimuth = 145
    camera.elevation = -20
    renderer.update_scene(env.data, camera=camera)
    scene = renderer.scene
    if scene.ngeom < scene.maxgeom:
        geom = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            geom,
            mujoco.mjtGeom.mjGEOM_SPHERE,
            np.array([env.success_tolerance_m] * 3),
            env.target_tcp_pos,
            np.eye(3).reshape(-1),
            np.array([0.15, 0.95, 0.25, 0.65]),
        )
        scene.ngeom += 1
    return Image.fromarray(renderer.render().copy())


def make_sheet(frames: list[Image.Image], errors: list[float], tolerance: float) -> Image.Image:
    width, height = frames[0].size
    indices = sorted(set([0, len(frames) // 2, len(frames) - 1]))
    sheet = Image.new("RGB", (width * len(indices), height + 170), "white")
    draw = ImageDraw.Draw(sheet)
    for column, index in enumerate(indices):
        sheet.paste(frames[index], (column * width, 0))
        draw.text((column * width + 12, height + 8), f"step {index} | TCP error {errors[index]:.3f} m", fill="black")
    left, right, top, bottom = 50, sheet.width - 30, height + 45, height + 145
    maximum = max(max(errors) * 1.05, tolerance * 2)
    y = lambda error: bottom - int(error / maximum * (bottom - top))
    x = lambda index: left + int(index / max(1, len(errors) - 1) * (right - left))
    draw.line((left, y(tolerance), right, y(tolerance)), fill="#28a745", width=2)
    draw.text((right - 170, y(tolerance) - 18), f"success <= {tolerance:.3f} m", fill="#187b32")
    draw.line([(x(i), y(error)) for i, error in enumerate(errors)], fill="#d12d35", width=4)
    draw.text((left, top - 15), "A-arm TCP distance to target", fill="black")
    return sheet


def visualize(scene: Path, output_dir: Path, checkpoint: Path | None = None, seed: int = 0) -> dict:
    env = TianjiAReachEnv(scene=scene, reset_noise_rad=0.03)
    observation, _ = env.reset(seed=seed)
    teacher = joint_goal_teacher(env.goal_rad, env.max_delta_rad)
    model = None
    if checkpoint is not None:
        from omi_hil_rl.training.executed_action_sac import DemoRegularizedSAC

        model = DemoRegularizedSAC.load(checkpoint, device="cpu")
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    errors = []
    success = False
    try:
        with mujoco.Renderer(env.model, height=480, width=640) as renderer:
            for step in range(env.max_steps + 1):
                frames.append(render_frame(renderer, env))
                errors.append(float(np.linalg.norm(observation["tcp_pos"] - observation["target_tcp_pos"])))
                if step == env.max_steps:
                    break
                action = teacher(observation) if model is None else model.predict(observation, deterministic=True)[0]
                observation, _, done, truncated, _ = env.step(action)
                if done or truncated:
                    success = bool(done)
                    frames.append(render_frame(renderer, env))
                    errors.append(float(np.linalg.norm(observation["tcp_pos"] - observation["target_tcp_pos"])))
                    break
        imageio.mimsave(output_dir / "episode.gif", [np.asarray(frame) for frame in frames], duration=0.13, loop=0)
        make_sheet(frames, errors, env.success_tolerance_m).save(output_dir / "reach_verification.png")
        result = {
            "scene": str(scene.resolve()),
            "controller": "scripted_teacher" if model is None else "trained_policy",
            "success": success,
            "steps": len(errors) - 1,
            "initial_tcp_error_m": errors[0],
            "final_tcp_error_m": errors[-1],
            "success_tolerance_m": env.success_tolerance_m,
            "tcp_errors_m": errors,
        }
        (output_dir / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        env.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/visualizations/a_reach"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(visualize(args.scene, args.output_dir, args.checkpoint, args.seed), indent=2))


if __name__ == "__main__":
    main()
