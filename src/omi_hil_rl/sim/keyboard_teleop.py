"""Terminal keyboard demonstrations for the MuJoCo A-arm reach task."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from omi_hil_rl.sim.tianji_a_reach import TianjiAReachEnv
from omi_hil_rl.training.recording import TransitionRecorder


def parse_jog(command: str) -> np.ndarray | None:
    """Map 1+..7- to one bounded joint increment; empty input holds."""
    command = command.strip()
    if not command:
        return np.zeros(7, dtype=np.float32)
    if len(command) != 2 or command[0] not in "1234567" or command[1] not in "+-":
        return None
    action = np.zeros(7, dtype=np.float32)
    action[int(command[0]) - 1] = 1.0 if command[1] == "+" else -1.0
    return action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/demonstrations/keyboard.jsonl"))
    args = parser.parse_args()
    env = TransitionRecorder(TianjiAReachEnv(scene=args.scene, reward_mode="progress"), args.output)
    try:
        observation, _ = env.reset()
        print("A arm simulation. Type 1+..7- and Enter to jog; Enter holds; r resets; q quits.")
        while True:
            distance = np.linalg.norm(observation["tcp_pos"] - observation["target_tcp_pos"])
            print(f"TCP distance {distance:.3f} m; joints {np.round(observation['state'][:7], 3)}")
            try:
                command = input("jog> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if command == "q":
                break
            if command == "r":
                observation, _ = env.reset()
                continue
            human = parse_jog(command)
            if human is None:
                print("Use 1+..7-, Enter, r, or q.")
                continue
            observation, _, done, truncated, info = env.step(
                np.zeros(7, dtype=np.float32), intervention_active=True, human_action=human
            )
            print(f"executed {info['executed_action']} | TCP error {info['tcp_error_m']:.3f} m")
            if done or truncated:
                print("success" if done else "time limit")
                observation, _ = env.reset()
    finally:
        env.close()
    print(f"Saved demonstrations to {args.output}")


if __name__ == "__main__":
    main()
