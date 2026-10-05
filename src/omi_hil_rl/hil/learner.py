"""Single replay writer and asynchronous SAC learner; no robot dependency."""
import argparse
import json
from pathlib import Path
import time

import torch

from omi_hil_rl.training.transition_replay import TransitionReplay
from .config import HILConfig, load_config
from .exchange import atomic_json, import_ready, owner_lock, publish
from .networks import SAC


def run_learner(run, config, *, recipe=None, pretrained=None, capacity=1000,
                batch_size=32, min_online=1, min_demo=1, updates=None, publish_every=50,
                device="cpu", wait_seconds=None):
    if min(capacity, batch_size, publish_every) < 1 or min_online < 0 or min_demo < 0 or (updates is not None and updates < 1):
        raise ValueError("invalid learner counts")
    if config.transport == "ros" and (min_demo < 1 or min_online < 1):
        raise ValueError("real training requires both demo and online streams")
    run = Path(run)
    contract = config.replay_contract()
    with owner_lock(run, "learner"):
        if (run / "learner.pt").exists():
            agent = SAC.restore(torch.load(run / "learner.pt", map_location=device, weights_only=True),
                                device=device, expected_contract=contract)
            if recipe is not None and recipe != agent.recipe:
                raise ValueError("resume recipe mismatch")
        else:
            recipe = recipe or (dict(encoder="synthetic-test") if config.transport == "fake" else None)
            if recipe is None or (config.transport == "ros" and pretrained is None):
                raise ValueError("new real learner requires --recipe and --pretrained frozen backbone weights")
            if pretrained and recipe.get("pretrained_sha256"):
                from omi_hil_rl.training.eef_bc_data import sha256
                if sha256(pretrained) != recipe["pretrained_sha256"]:
                    raise ValueError("pretrained backbone hash mismatch")
            weights = torch.load(pretrained, map_location="cpu", weights_only=True) if pretrained else None
            agent = SAC(recipe, contract, device=device, pretrained=weights)
        replay_dir = run / "replay"
        replay = (TransitionReplay.reopen(replay_dir, expected_contract=contract, prefetch=False)
                  if replay_dir.exists() else TransitionReplay(replay_dir, contract, capacity, prefetch=False))
        try:
            publish(run, agent)
            started = time.monotonic()
            target_updates = None if updates is None else agent.updates + updates
            print("learner 已发布初始策略；等待保留回合和训练数据。", flush=True)
            while target_updates is None or agent.updates < target_updates:
                if wait_seconds is not None and time.monotonic() - started >= wait_seconds:
                    raise TimeoutError("learner run deadline reached before requested updates")
                imported = import_ready(run, replay)
                counts = replay.buffer.stream_counts()
                ready = counts["online"] >= min_online and counts["demonstration"] >= min_demo
                if ready and replay.buffer.size():
                    metrics = agent.update(replay.buffer.sample(batch_size))
                    if agent.updates % publish_every == 0:
                        publish(run, agent)
                    if agent.updates == 1 or agent.updates % 10 == 0:
                        print(json.dumps(dict(metrics, streams=counts)), flush=True)
                    atomic_json(run / "status.json", dict(metrics, streams=counts, imported=imported))
                else:
                    atomic_json(run / "status.json", dict(update=agent.updates, streams=counts, waiting=True, imported=imported))
                    time.sleep(.05)
            publish(run, agent)
            return dict(updates=agent.updates, streams=replay.buffer.stream_counts())
        finally:
            replay.close()
            publish(run, agent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--pretrained", type=Path)
    parser.add_argument("--capacity", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--min-online", type=int, default=1)
    parser.add_argument("--min-demo", type=int, default=1)
    parser.add_argument("--updates", type=int)
    parser.add_argument("--publish-every", type=int, default=50)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--wait-seconds", type=float)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    result = run_learner(args.run, load_config(args.config) if args.config else HILConfig(),
        recipe=json.loads(args.recipe.read_text()) if args.recipe else None, pretrained=args.pretrained,
        capacity=args.capacity, batch_size=args.batch_size, min_online=args.min_online,
        min_demo=args.min_demo, updates=args.updates, publish_every=args.publish_every,
        device=args.device, wait_seconds=args.wait_seconds)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
