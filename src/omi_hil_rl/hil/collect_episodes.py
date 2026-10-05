"""Human-only RL episode collection; no learner, checkpoint or random policy."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import signal
import time

import numpy as np

from .config import HILConfig, load_config
from .environment import RealHILEnv, InteractionUnavailable, EpisodeTimeout, EpisodeSuccess
from .exchange import atomic_json, owner_lock
from .async_spool import AsyncEpisodeSpool


def collect(run, config, transport, *, episodes=100000):
    """Valid successes AND timeouts are retained as online human experience."""
    if episodes < 1:
        raise ValueError('positive episode limit required')
    run = Path(run)
    run.mkdir(parents=True, exist_ok=False)
    transport.allow_manual_reset = True
    transport.collect_human = True
    env = RealHILEnv(transport, config)
    results, spool = [], None
    atomic_json(run / 'session.json', dict(mode='human_rl_episodes', config=asdict(config),
        contract=config.replay_contract(), policy='none', reset_actions_in_replay=False,
        rgb_max_age_ns=getattr(getattr(transport, 'runtime', None), 'rgb_max_age_ns', None),
        receiver=getattr(transport, 'receiver_info', None)))
    try:
        with owner_lock(run, 'actor'):
            for _ in range(episodes):
                spool = None
                print('WAIT_START: RB可人工复位；松开再按开始键启动新回合。', flush=True)
                try:
                    obs, reset_info = env.reset()
                except InteractionUnavailable as exc:
                    results.append(dict(keep=False, count=0, reason=str(exc), start_failed=True))
                    atomic_json(run / 'summary.json', dict(episodes=results, closed=False))
                    continue
                spool = AsyncEpisodeSpool(run, reset_info['episode'], config.replay_contract(), origin='online')
                print('ACTIVE: RB+摇杆控制；松开RB为零动作；成功键结束，否则到时停止。', flush=True)
                try:
                    while True:
                        spool.check()
                        nxt, reward, terminated, truncated, info = env.step(np.zeros(6, np.float32))
                        if info['action_source'] != 'human':
                            raise InteractionUnavailable('human collection cannot contain policy actions')
                        spool.append(obs, nxt, reward, terminated, truncated, info)
                        obs = nxt
                        if terminated or truncated:
                            result = spool.finish(env.review(), reason=info['reason'],
                                                  tick=getattr(transport, 'idle_tick', None))
                            break
                except (EpisodeTimeout, EpisodeSuccess) as exc:
                    transport.stop()
                    if spool.count:
                        spool.finish_valid_prefix(success=isinstance(exc, EpisodeSuccess))
                    keep = env.review() if spool.count else False
                    result = spool.finish(keep, reason=str(exc), tick=getattr(transport, 'idle_tick', None))
                    env.phase = 'idle'
                except InteractionUnavailable as exc:
                    transport.stop()
                    result = spool.finish(False, reason=str(exc), tick=getattr(transport, 'idle_tick', None))
                    env.phase = 'idle'
                results.append(result)
                spool = None
                atomic_json(run / 'summary.json', dict(episodes=results, closed=False))
                print(json.dumps(dict(state='WAIT_RESET', count=result['count'], keep=result['keep'],
                    success=result['episode_success'], reason=result['reason'])), flush=True)
    finally:
        # Stop first, then preserve an interrupted prefix for audit, never train on it.
        try:
            transport.stop()
        finally:
            try:
                if spool is not None:
                    results.append(spool.finish(False, reason='interrupted_or_error'))
                atomic_json(run / 'summary.json', dict(episodes=results, closed=True))
            finally:
                env.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--episode-seconds', type=float, default=15.)
    parser.add_argument('--episodes', type=int, default=100000)
    parser.add_argument('--gamepad', default='/dev/input/js0')
    parser.add_argument('--rgb-max-age-ms', type=float, default=500.)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; use a new directory')
    config = replace(load_config(args.config) if args.config else HILConfig(transport='ros', wrist_camera='required'),
                     review='auto', episode_seconds=args.episode_seconds)
    if config.transport != 'ros' or args.episodes < 1:
        parser.error('ROS config and positive episode count required')
    receiver = None
    if args.execute:
        from omi_hil_rl.real.receiver_preflight import inspect_receiver
        from omi_hil_rl.real.linux_gamepad import LinuxGamepad
        pad = LinuxGamepad(args.gamepad)
        try:
            if not pad.poll():
                parser.error('gamepad unavailable: ' + pad.error)
            required = (config.start_button, config.success_button, config.stop_button)
            if not set(required) <= set(pad.button_map):
                parser.error('configured episode buttons are absent on this gamepad')
        finally:
            pad.close()
        receiver = inspect_receiver(require_manual_receipts=True)
    from .ros_transport import RosTransport
    from omi_hil_rl.training.eef_bc_grid import GridProfile
    transport = RosTransport(config, GridProfile(config.wrist_camera).CONTRACT, execute=args.execute,
        gamepad=args.gamepad, topic=receiver['manual_topic'] if receiver else '/omi/action/manual_decision',
        convention=config.sdk_convention, rgb_max_age_ms=args.rgb_max_age_ms)
    transport.competing_topics = ['/omi/action/decision', '/omi/action/manual_decision']
    transport.receiver_info = receiver
    if not args.execute:
        try:
            transport.reset_history()
            obs, stamp = transport.observe(time.monotonic() + config.episode_seconds)
            print(json.dumps(dict(preview=True, observation_time_ns=stamp,
                                 shapes={k: list(v.shape) for k, v in obs.items()})))
        finally:
            transport.close()
        return
    # One interrupt initiates orderly shutdown; repeated interrupts do not break saving.
    interrupted = False
    def stop(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        collect(args.output, config, transport, episodes=args.episodes)
    except KeyboardInterrupt:
        print('已停止；完整回合已保存，未完成回合仅保留审计、不入训练池。', flush=True)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
