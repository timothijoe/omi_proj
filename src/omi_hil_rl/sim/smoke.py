"""Run one headless policy/human intervention episode on the surrogate model."""

from __future__ import annotations

import json

import numpy as np

from omi_hil_rl.sim.tianji_surrogate import TianjiSurrogateEnv


def main() -> None:
    env = TianjiSurrogateEnv()
    try:
        observation, _ = env.reset()
        transitions = []
        for step in range(env.max_steps):
            error = env.goal_rad - observation["state"][:7]
            policy_action = np.clip(error / env.max_delta_rad, -1.0, 1.0)
            intervene = step == 2
            human_action = np.zeros(7) if intervene else None
            next_observation, reward, terminated, truncated, info = env.step(
                policy_action,
                intervention_active=intervene,
                human_action=human_action,
            )
            transitions.append(
                {
                    "step": step,
                    "source": info["action_source"],
                    "policy_action": info["policy_action"].tolist(),
                    "executed_action": info["executed_action"].tolist(),
                    "reward": reward,
                    "goal_error_rad": info["goal_error_rad"],
                }
            )
            observation = next_observation
            if terminated or truncated:
                break
        print(json.dumps({
            "model": "uncalibrated_7dof_surrogate",
            "steps": len(transitions),
            "intervention_steps": sum(t["source"] == "human" for t in transitions),
            "success": terminated,
            "truncated": truncated,
            "last_goal_error_rad": transitions[-1]["goal_error_rad"],
        }, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
