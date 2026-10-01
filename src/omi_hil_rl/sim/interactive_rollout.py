"""Stepwise human intervention while a trained policy runs in MuJoCo."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from omi_hil_rl.sim.keyboard_teleop import parse_jog
from omi_hil_rl.sim.tianji_a_reach import TianjiAReachEnv
from omi_hil_rl.training.executed_action_sac import DemoRegularizedSAC
from omi_hil_rl.training.recording import TransitionRecorder


def step_with_command(env, policy_action: np.ndarray, command: str):
    """Enter uses the policy; 1+..7- or h overrides with a human action."""
    command = command.strip().lower()
    if command == "":
        return env.step(policy_action)
    human = np.zeros(7, dtype=np.float32) if command == "h" else parse_jog(command)
    if human is None:
        raise ValueError("use Enter for policy, 1+..7- to intervene, or h to hold")
    return env.step(policy_action, intervention_active=True, human_action=human)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/demonstrations/interactive_rollout.jsonl"))
    args = parser.parse_args()
    model = DemoRegularizedSAC.load(args.checkpoint, device="cpu")
    env = TransitionRecorder(TianjiAReachEnv(scene=args.scene), args.output)
    try:
        observation, _ = env.reset()
        print("Enter: policy step | 1+..7-: intervene | h: human hold | r: reset | q: quit")
        while True:
            distance = np.linalg.norm(observation["tcp_pos"] - observation["target_tcp_pos"])
            policy_action, _ = model.predict(observation, deterministic=True)
            print(f"TCP distance {distance:.3f} m | policy {np.round(policy_action, 2)}")
            try:
                command = input("action> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if command == "q":
                break
            if command == "r":
                observation, _ = env.reset()
                continue
            try:
                observation, _, done, truncated, info = step_with_command(env, policy_action, command)
            except ValueError as exc:
                print(exc)
                continue
            print(f"{info['action_source']} executed {np.round(info['executed_action'], 2)} "
                  f"| TCP error {info['tcp_error_m']:.3f} m")
            if done or truncated:
                print("success" if done else "time limit")
                observation, _ = env.reset()
    finally:
        env.close()
    print(f"Saved rollout to {args.output}")


if __name__ == "__main__":
    main()
