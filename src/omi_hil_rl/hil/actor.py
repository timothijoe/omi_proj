"""Episode actor. Fake by default; ROS preview unless --execute is explicit."""
import argparse
import json
from pathlib import Path
import time

import torch

from .config import HILConfig, load_config
from .environment import FakeTransport, RealHILEnv, InteractionUnavailable, EpisodeTimeout
from .exchange import EpisodeSpool, owner_lock
from .networks import load_actor


def run_actor(run, config, *, episodes=1, device="cpu", execute=False,
              gamepad="/dev/input/js0", offline_demo=False, success_step=5, deterministic=False):
    if episodes < 1:
        raise ValueError("episodes must be positive")
    run = Path(run)
    contract = config.replay_contract()
    with owner_lock(run, "actor"):
        print("等待 learner 发布 actor.pt", flush=True)
        while not (run / "actor.pt").exists():
            time.sleep(.1)
        actor, version, recipe = load_actor(run / "actor.pt", contract, device)
        if config.transport == "fake":
            if offline_demo:
                raise ValueError("fake policy episodes cannot be labelled human demos")
            transport = FakeTransport(config, success_step=success_step)
        else:
            from .ros_transport import RosTransport
            transport = RosTransport(config, recipe["base_contract"], execute=execute, gamepad=gamepad,
                                     convention=recipe["sdk_convention"])
        if offline_demo:
            transport.human_only = True
        env = RealHILEnv(transport, config)
        results = []
        try:
            if config.transport == "ros" and not execute:
                # Read-only preview: no publisher and no replay-compatible transitions.
                transport.reset_history()
                for _ in range(episodes):
                    obs, stamp = transport.observe(time.monotonic() + config.episode_seconds)
                    with torch.inference_mode():
                        action, _ = actor.sample({k: torch.as_tensor(v, device=device)[None] for k, v in obs.items()}, True)
                    print(json.dumps(dict(preview=True, observation_time_ns=stamp, action=action[0].cpu().tolist())), flush=True)
                    time.sleep(.1)
                return results
            for _ in range(episodes):
                # Atomic published weights; swap only while stopped at an episode boundary.
                actor, version, _ = load_actor(run / "actor.pt", contract, device)
                try:
                    observation, reset_info = env.reset()
                except InteractionUnavailable as exc:
                    print(json.dumps(dict(start_failed=str(exc))), flush=True)
                    continue
                spool = EpisodeSpool(run, reset_info["episode"], contract,
                    origin="offline_demo" if offline_demo else "online", policy_version=version)
                try:
                    while True:
                        with torch.inference_mode():
                            action, _ = actor.sample({k: torch.as_tensor(v, device=device)[None] for k, v in observation.items()}, deterministic=deterministic)
                        next_observation, reward, terminated, truncated, info = env.step(action[0].cpu().numpy())
                        if offline_demo and info["action_source"] != "human":
                            raise InteractionUnavailable("demo mode requires RB human control for every step")
                        spool.append(observation, next_observation, reward, terminated, truncated, info)
                        observation = next_observation
                        if terminated or truncated:
                            keep = env.review()
                            if offline_demo and not terminated:
                                keep = False
                            result = spool.finish(keep, reason=info["reason"])
                            break
                except EpisodeTimeout as exc:
                    transport.stop()
                    if spool.count:
                        spool.truncate_valid_prefix()
                        keep = env.review()
                        result = spool.finish(keep and not offline_demo, reason="timeout_between_commands")
                    else:
                        result = spool.finish(False, reason=str(exc))
                        env.phase = "idle"
                except InteractionUnavailable as exc:
                    transport.stop()
                    result = spool.finish(False, reason=str(exc))
                    env.phase = "idle"
                results.append(result)
                print(json.dumps(dict(episode=result["episode"], count=result["count"], keep=result["keep"],
                                      success=result["episode_success"], reason=result["reason"])), flush=True)
        finally:
            env.close()
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--execute", action="store_true", help="publish tagged real-robot deltas; requires ROS config")
    parser.add_argument("--gamepad", default="/dev/input/js0")
    parser.add_argument("--deterministic", action="store_true", help="use mean action, e.g. for BC evaluation")
    parser.add_argument("--offline-demo", action="store_true", help="successful all-human episodes go to demo stream only")
    parser.add_argument("--fake-success-step", type=int, default=5)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    config = load_config(args.config) if args.config else HILConfig()
    if args.execute and config.transport != "ros":
        parser.error("--execute requires a ROS config")
    run_actor(args.run, config, episodes=args.episodes, device=args.device, execute=args.execute,
              gamepad=args.gamepad, offline_demo=args.offline_demo, success_step=args.fake_success_step, deterministic=args.deterministic)


if __name__ == "__main__":
    main()
