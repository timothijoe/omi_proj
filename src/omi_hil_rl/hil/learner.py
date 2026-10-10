"""Single replay writer and asynchronous SAC learner; no robot dependency."""
import argparse
import json
import math
from pathlib import Path
import time

import torch

from omi_hil_rl.training.transition_replay import TransitionReplay
from omi_hil_rl.training.dual_replay import open_replay
from .config import HILConfig, load_config
from .exchange import atomic_json, import_ready, owner_lock, publish
from .networks import SAC
from .shutdown import graceful_stop
from .telemetry import TelemetryWriter


def run_learner(run, config, *, recipe=None, pretrained=None, capacity=1000,
                batch_size=256, min_online=1, min_demo=1, updates=None, publish_every=50,
                device="cpu", wait_seconds=None, should_stop=lambda: False, alternating_episode=None,
                update_delay=0., recorded_sources=(), max_updates_per_transition=None):
    if min(capacity, batch_size, publish_every) < 1 or min_online < 0 or min_demo < 0 or (updates is not None and updates < 1):
        raise ValueError("invalid learner counts")
    if config.transport == "ros" and (min_demo < 1 or min_online < 1):
        raise ValueError("real training requires both demo and online streams")
    if not 0 <= update_delay < float('inf'):
        raise ValueError('update delay must be finite and nonnegative')
    if max_updates_per_transition is not None and (not math.isfinite(max_updates_per_transition) or max_updates_per_transition <= 0):
        raise ValueError('max_updates_per_transition must be finite and positive')
    run = Path(run)
    schedule = run / 'alternating_state.json'
    if schedule.exists():
        state = json.loads(schedule.read_text())
        if (alternating_episode is None or state.get('phase') != 'TRAINING' or
                (state.get('task') or {}).get('episode') != alternating_episode):
            raise ValueError('alternating run: learner may only run the current scheduler task')
    contract = config.replay_contract()
    with owner_lock(run, "learner"), TelemetryWriter(run, 'learner') as telemetry:
        telemetry.update(batch_size=batch_size, min_online=min_online, min_demo=min_demo,
                         publish_every=publish_every, device=device)
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
        replay = (open_replay(replay_dir, expected_contract=contract)
                  if replay_dir.exists() else TransitionReplay(replay_dir, contract, capacity, prefetch=False))
        if recorded_sources:
            if not getattr(replay, 'is_cached', False):
                replay.close()
                raise ValueError('recorded sources require cached replay')
            replay.add_sources(recorded_sources)
        update_in_progress = False
        imported_total, actor_updates, rl_updates = 0, 0, 0
        last_update_completed = None
        def publish_monitored():
            before = time.monotonic()
            publish(run, agent)
            telemetry.update(published_version=agent.updates, published_ns=time.time_ns(),
                             publish_ms=(time.monotonic()-before)*1000)
            telemetry.event('weights_published', version=agent.updates)
        try:
            if max_updates_per_transition is not None and not getattr(replay, 'is_cached', False):
                raise ValueError('update budget requires the cached replay persistent catalog')
            if getattr(replay, 'is_cached', False) and max(min_online, min_demo) > replay.buffer_size:
                raise ValueError('resident cache cannot reach requested training data thresholds')
            if getattr(replay, 'is_dual', False) and (batch_size < 2 or batch_size % 2):
                raise ValueError('dual replay requires an even batch size >= 2')
            publish_monitored()
            started = time.monotonic()
            target_updates = None if updates is None else agent.updates + updates
            print("learner 已发布初始策略；等待保留回合和训练数据。", flush=True)
            while target_updates is None or agent.updates < target_updates:
                if should_stop():
                    break
                if wait_seconds is not None and time.monotonic() - started >= wait_seconds:
                    raise TimeoutError("learner run deadline reached before requested updates")
                telemetry.update(phase='IMPORTING')
                import_started = time.monotonic()
                imported = import_ready(run, replay)
                import_ms = (time.monotonic()-import_started)*1000
                imported_total += imported
                if imported:
                    telemetry.event('replay_imported', count=imported)
                counts = replay.buffer.stream_counts()
                replay_stats = replay.storage_stats() if getattr(replay, 'is_cached', False) else None
                if replay_stats is not None:
                    telemetry.update(replay=replay_stats)
                ready = counts["online"] >= min_online and counts["demonstration"] >= min_demo
                if getattr(replay, 'is_dual', False):
                    ready = ready and counts['online'] > 0 and counts['demonstration'] > 0
                demo_warmup = (getattr(replay, 'is_dual', False) and agent.freeze_encoder and
                               agent.updates < agent.critic_warmup_updates and
                               counts['demonstration'] >= max(1, min_demo))
                ready = ready or demo_warmup
                budget_exhausted = False
                if max_updates_per_transition is not None:
                    allowance = agent.critic_warmup_updates+int(replay_stats['catalog_online']*max_updates_per_transition)
                    budget_exhausted = agent.updates >= allowance
                    ready = ready and not budget_exhausted
                    telemetry.update(update_budget=allowance, max_updates_per_transition=max_updates_per_transition)
                if ready and replay.buffer.size():
                    telemetry.update(phase='TRAINING', streams=counts, waiting_reason=None)
                    update_started = time.monotonic()
                    update_in_progress = True
                    batch = (replay.buffer.sample_human(batch_size) if demo_warmup
                             else replay.buffer.sample(batch_size))
                    metrics = (agent.update(batch, human_batch=replay.buffer.sample_human(batch_size))
                               if agent.bc_weight else agent.update(batch))
                    update_in_progress = False
                    metrics['demo_only_warmup'] = demo_warmup
                    actor_updates += int('actor_loss' in metrics)
                    rl_updates += int(not demo_warmup)
                    telemetry.update(metrics=dict(metrics), update=agent.updates,
                        actor_updates_this_process=actor_updates, imported_this_process=imported_total,
                        rl_updates_this_process=rl_updates,
                        import_ms=import_ms, update_ms=(time.monotonic()-update_started)*1000,
                        warmup_remaining=max(0, agent.critic_warmup_updates-agent.updates))
                    if agent.updates % publish_every == 0:
                        publish_monitored()
                    if agent.updates == 1 or agent.updates % 10 == 0:
                        print(json.dumps(dict(metrics, streams=counts)), flush=True)
                    atomic_json(run / "status.json", dict(metrics, streams=counts, imported=imported, replay=replay_stats))
                    completed_at = time.monotonic()
                    telemetry.update(update_hz=1/(completed_at-last_update_completed) if last_update_completed else None)
                    last_update_completed = completed_at
                    if update_delay:
                        # Optional resource pacing, not a data/update-ratio budget.
                        end_delay = time.monotonic() + update_delay
                        while time.monotonic() < end_delay and not should_stop():
                            time.sleep(min(.05, max(0., end_delay - time.monotonic())))
                else:
                    telemetry.update(phase='WAITING', update=agent.updates, streams=counts,
                        imported_this_process=imported_total, import_ms=import_ms,
                        waiting_reason=('waiting_for_update_budget' if budget_exhausted else
                                        'waiting_for_online' if counts['online'] < min_online else 'waiting_for_demo'),
                        warmup_remaining=max(0, agent.critic_warmup_updates-agent.updates))
                    atomic_json(run / "status.json", dict(update=agent.updates, streams=counts, waiting=True, imported=imported,
                        waiting_for_online=counts['online'] < min_online,
                        critic_warmup_remaining=max(0, agent.critic_warmup_updates-agent.updates), replay=replay_stats,
                        waiting_for_update_budget=budget_exhausted))
                    time.sleep(.05)
            publish_monitored()
            return dict(updates=agent.updates, streams=replay.buffer.stream_counts())
        finally:
            replay.close()
            # OOM or another exception may have interrupted one of several
            # optimizer steps. Keep the last good checkpoint in that case.
            if not update_in_progress:
                publish_monitored()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--pretrained", type=Path)
    parser.add_argument("--capacity", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--min-online", type=int, default=1)
    parser.add_argument("--min-demo", type=int, default=1)
    parser.add_argument("--updates", type=int)
    parser.add_argument("--publish-every", type=int, default=50)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--wait-seconds", type=float)
    parser.add_argument('--alternating-episode', help=argparse.SUPPRESS)
    parser.add_argument('--update-delay', type=float, default=0.)
    parser.add_argument('--recorded-source', type=Path, action='append', default=[],
                        help='additional read-only recorded run, cached replay only')
    parser.add_argument('--max-updates-per-transition', type=float,
                        help='optional cumulative Critic budget per cataloged online transition, plus warmup; cached only')
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    with graceful_stop() as should_stop:
        result = run_learner(args.run, load_config(args.config) if args.config else HILConfig(),
            recipe=json.loads(args.recipe.read_text()) if args.recipe else None, pretrained=args.pretrained,
            capacity=args.capacity, batch_size=args.batch_size, min_online=args.min_online,
            min_demo=args.min_demo, updates=args.updates, publish_every=args.publish_every,
            device=args.device, wait_seconds=args.wait_seconds, should_stop=should_stop,
            alternating_episode=args.alternating_episode, update_delay=args.update_delay, recorded_sources=args.recorded_source,
            max_updates_per_transition=args.max_updates_per_transition)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
