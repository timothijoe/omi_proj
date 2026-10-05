"""Extract observation statistics/contract from BC; never copy BC control heads."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import torch

from .config import HILConfig
from omi_hil_rl.training.eef_bc_stack import NO_JOINT_VERSION
from omi_hil_rl.training.eef_bc_data import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bc-checkpoint", type=Path, required=True)
    parser.add_argument("--pretrained", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episode-seconds", type=float, default=15.)
    parser.add_argument("--eef-reference", choices=("raw", "bag-baseline-v1"), default="raw")
    parser.add_argument("--sdk-convention", choices=("sdk-x-forward-z-left", "sdk-base-aligned"), default="sdk-x-forward-z-left")
    args = parser.parse_args()
    source = torch.load(args.bc_checkpoint, map_location="cpu", weights_only=True)["config"]
    if source["version"] != NO_JOINT_VERSION:
        raise ValueError("a no-joint current9stack checkpoint is required")
    config = HILConfig(transport="ros", episode_seconds=args.episode_seconds,
        eef_reference=args.eef_reference, wrist_camera=source["base_contract"]["wrist_camera"], sdk_convention=args.sdk_convention)
    recipe = dict(encoder="current9stack", base_contract=source["base_contract"], normalization=source["normalization"],
        sdk_convention=args.sdk_convention, pretrained_sha256=sha256(args.pretrained),
        normalization_source_sha256=sha256(args.bc_checkpoint), control_head_initialization="scratch")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    (args.output / "recipe.json").write_text(json.dumps(recipe, indent=2) + "\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
