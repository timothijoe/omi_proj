"""Evaluate a saved simulation policy without scripted interventions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from omi_hil_rl.training.executed_action_sac import DemoRegularizedSAC
from omi_hil_rl.training.sim_train import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--scene", type=Path, help="External cooking project MJCF used for A-arm training")
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("--episodes must be positive")
    model = DemoRegularizedSAC.load(args.checkpoint, device="cpu")
    print(json.dumps(evaluate(model, args.episodes, seed=args.seed, scene=args.scene), indent=2))


if __name__ == "__main__":
    main()
