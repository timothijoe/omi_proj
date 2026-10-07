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


def collect(run, config, transport, *, episodes=100000, resume=False):
    """Resume only at an episode boundary; never resume physical motion."""
    run = Path(run)
    if episodes < 1:
        raise ValueError('positive episode limit required')
    if resume:
        if not (run / 'session.json').is_file():
            raise ValueError('resume requires an existing session.json')
    else:
        run.mkdir(parents=True, exist_ok=False)
    with owner_lock(run, 'actor'):
        results = []
        if resume:
            session = json.loads((run / 'session.json').read_text())
            if session['contract'] != config.replay_contract() or session.get('mode') != 'human_rl_episodes':
                raise ValueError('resume collection contract/mode mismatch')
            # Manifests, not summary.json, are authoritative after a process crash.
            for directory in sorted((run / 'episodes').glob('*')):
                ready, discarded = directory / 'ready.json', directory / 'discarded.json'
                if ready.exists() or discarded.exists():
                    results.append(json.loads((ready if ready.exists() else discarded).read_text()))
                elif (directory / 'staging.json').exists():
                    orphan = json.loads((directory / 'staging.json').read_text())
                    orphan.update(keep=False, episode_success=False, count=len(list(directory.glob('*.npz'))),
                                  reason='process_interrupted_unfinished_episode')
                    atomic_json(discarded, orphan)
                    results.append(orphan)
            print(f'RESUME: 已发现 {len(results)} 个历史回合；未完成回合仅审计；等待重新按开始键。', flush=True)
        return _collect(run, config, transport, episodes=episodes, results=results, resume=resume)


def collect_periodic(run, config, transport, *, episodes=100000, resume=False):
    """Human-only 10Hz control with post-episode receipt/observation validation."""
    from .periodic_control import run_periodic
    run = Path(run)
    if episodes < 1:
        raise ValueError('positive episode limit required')
    if not resume:
        run.mkdir(parents=True, exist_ok=False)
    with owner_lock(run, 'actor'):
        if resume:
            session = json.loads((run / 'session.json').read_text())
            if (session.get('mode') != 'human_rl_periodic_v1' or
                    session.get('contract') != config.replay_contract()):
                raise ValueError('periodic collection contract/mode mismatch')
        else:
            atomic_json(run / 'session.json', dict(mode='human_rl_periodic_v1',
                config=asdict(config), contract=config.replay_contract(), policy='none',
                reset_actions_in_replay=False, action_semantics='accepted_command',
                control_mode='periodic_100ms_posthoc_validation',
                receiver=getattr(transport, 'receiver_info', None)))
        transport.collect_human = True

        class HumanPeriodicActor:
            def __init__(self):
                self.run, self.config, self.transport, self.version = run, config, transport, 0

            def load(self):
                pass

            def close_pipeline(self):
                pass

            def state(self, phase, **details):
                print('HUMAN_PERIODIC: ' + json.dumps(dict(phase=phase, **details),
                    ensure_ascii=False), flush=True)

            def finished(self, result):
                print('HUMAN_PERIODIC_READY: ' + json.dumps(result, ensure_ascii=False), flush=True)

        run_periodic(HumanPeriodicActor(), episodes, training=True)


def _collect(run, config, transport, *, episodes, results, resume,
             action_provider=None, episode_finished=None, policy_version=lambda: 0,
             close_transport=True, phase_hook=lambda phase: None):
    """Valid successes AND timeouts are retained as online human experience."""
    if episodes < 1:
        raise ValueError('positive episode limit required')
    run = Path(run)
    transport.timing_report_path = run / 'last_command_timing_failure.json'
    transport.pairing_report_path = run / 'last_command_pairing_failure.json'
    transport.allow_manual_reset = True
    transport.collect_human = action_provider is None
    env = RealHILEnv(transport, config)
    spool = None
    if not resume:
        atomic_json(run / 'session.json', dict(mode='human_rl_episodes', config=asdict(config),
            contract=config.replay_contract(), policy='none', reset_actions_in_replay=False,
            rgb_max_age_ns=getattr(getattr(transport, 'runtime', None), 'rgb_max_age_ns', None),
            receiver=getattr(transport, 'receiver_info', None)))
    try:
        for _ in range(episodes):
            spool = None
            phase_hook('WAIT_START')
            home_hint = 'Back可自动回home；' if getattr(transport, 'home', None) is not None else ''
            print('WAIT_START: RB+摇杆可人工复位；' + home_hint + '松开再按开始键启动新回合。', flush=True)
            try:
                obs, reset_info = env.reset()
            except InteractionUnavailable as exc:
                results.append(dict(keep=False, count=0, reason=str(exc), start_failed=True))
                atomic_json(run / 'summary.json', dict(episodes=results, closed=False))
                print('START_FAILED: ' + str(exc) + '；已停止，等待重新按开始键。', flush=True)
                continue
            spool = AsyncEpisodeSpool(run, reset_info['episode'], config.replay_contract(), origin='online',
                                      policy_version=policy_version())
            phase_hook('ACTIVE')
            print('ACTIVE: RB+摇杆控制；松开RB为' + ('零动作' if action_provider is None else '模型控制') +
                  '；308成功、307提前结束，否则到时停止。', flush=True)
            try:
                while True:
                    spool.check()
                    diagnostic_start = time.monotonic_ns()
                    diagnostic_clock = getattr(getattr(transport, 'node', None), 'get_clock', None)
                    diagnostic_ros = diagnostic_clock().now().nanoseconds if diagnostic_clock else None
                    action = np.zeros(6, np.float32) if action_provider is None else action_provider(obs)
                    transport.action_timing = dict(
                        anchor_ns=env.previous_stamp,
                        age_before_inference_ms=(diagnostic_ros-env.previous_stamp)/1e6 if diagnostic_ros is not None else None,
                        inference_wall_ms=(time.monotonic_ns()-diagnostic_start)/1e6)
                    pipeline = getattr(transport, 'policy_pipeline', None)
                    candidate = pipeline.get(env.previous_stamp) if pipeline is not None else None
                    if candidate is not None:
                        transport.action_timing.update(background_inference_wall_ms=candidate[1],
                                                       inference_mode='precomputed_exact_observation')
                    nxt, reward, terminated, truncated, info = env.step(action)
                    info['policy_version'] = policy_version()
                    if action_provider is None and info['action_source'] != 'human':
                        raise InteractionUnavailable('human collection cannot contain policy actions')
                    spool.append(obs, nxt, reward, terminated, truncated, info)
                    obs = nxt
                    if terminated or truncated:
                        phase_hook('SAVING')
                        result = spool.finish(env.review(), reason=info['reason'],
                                              tick=getattr(transport, 'idle_tick', None))
                        break
            except (EpisodeTimeout, EpisodeSuccess) as exc:
                transport.stop()
                phase_hook('SAVING')
                if spool.count:
                    spool.finish_valid_prefix(success=isinstance(exc, EpisodeSuccess))
                keep = env.review() if spool.count else False
                result = spool.finish(keep, reason=str(exc), tick=getattr(transport, 'idle_tick', None))
                env.phase = 'idle'
            except InteractionUnavailable as exc:
                transport.stop()
                phase_hook('SAVING')
                result = spool.finish(False, reason=str(exc), tick=getattr(transport, 'idle_tick', None))
                env.phase = 'idle'
            results.append(result)
            spool = None
            atomic_json(run / 'summary.json', dict(episodes=results, closed=False))
            print(json.dumps(dict(state='WAIT_RESET', count=result['count'], keep=result['keep'],
                success=result['episode_success'], reason=result['reason'])), flush=True)
            if episode_finished is not None:
                episode_finished(result)
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
                if close_transport:
                    env.close()
    return results


def main():
    from omi_hil_rl.real.gamepad_gripper import (
        BTN_A, BTN_B, add_gripper_arguments, calibration_from_args, GamepadGripper)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--episode-seconds', type=float, default=15.)
    parser.add_argument('--episodes', type=int, default=100000)
    parser.add_argument('--gamepad', default='/dev/input/js0')
    parser.add_argument('--home-button-code', type=int, default=314,
                        help='Back key for automatic home between episodes (default: 314)')
    add_gripper_arguments(parser)
    project_root = Path(__file__).resolve().parents[3]
    parser.set_defaults(
        gripper_server='192.168.14.11:55551',
        gripper_sdk_root=project_root / 'local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py',
        gripper_calibration=project_root / 'tutorials/gripper_limits.json')
    parser.add_argument('--no-gripper', action='store_true', help='Disable A/B gripper control')
    parser.add_argument('--rgb-max-age-ms', type=float, default=500.)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--control-mode', choices=('receipt', 'periodic'), default='receipt',
                        help='periodic sends every 100ms and validates receipts/observations after each episode')
    parser.add_argument('--resume', action='store_true', help='append new episodes to an existing matching session')
    args = parser.parse_args()
    if args.no_gripper:
        args.gripper_server = None
    calibration = calibration_from_args(args, parser)
    if args.output.exists() and not args.resume:
        parser.error('output already exists; use a new directory or --resume')
    if args.resume and not (args.output / 'session.json').is_file():
        parser.error('--resume requires an existing session.json')
    config = replace(load_config(args.config) if args.config else HILConfig(transport='ros', wrist_camera='required'),
                     review='auto', episode_seconds=args.episode_seconds)
    if config.transport != 'ros' or args.episodes < 1:
        parser.error('ROS config and positive episode count required')
    episode_buttons = (config.start_button, config.success_button, config.stop_button,
                       config.keep_button, config.discard_button, 311)
    if args.home_button_code < 0 or args.home_button_code in episode_buttons:
        parser.error('home button must be distinct from episode buttons and RB')
    if args.gripper_server and {BTN_A, BTN_B} & {config.start_button, config.success_button, config.stop_button}:
        parser.error('A/B gripper buttons must be distinct from episode start/success/stop')
    if args.resume:
        session = json.loads((args.output/'session.json').read_text())
        expected_mode = 'human_rl_periodic_v1' if args.control_mode == 'periodic' else 'human_rl_episodes'
        if session.get('mode') != expected_mode or session['contract'] != config.replay_contract():
            parser.error('resume collection contract/mode mismatch; use the original configuration')
    receiver = None
    if args.execute:
        from omi_hil_rl.real.receiver_preflight import inspect_receiver
        from omi_hil_rl.real.linux_gamepad import LinuxGamepad
        pad = LinuxGamepad(args.gamepad)
        try:
            if not pad.poll():
                parser.error('gamepad unavailable: ' + pad.error)
            required = {config.start_button, config.success_button, config.stop_button, args.home_button_code}
            if args.gripper_server:
                required.update((BTN_A, BTN_B))
            if not required <= set(pad.button_map):
                parser.error('configured episode/home/gripper buttons are absent on this gamepad')
        finally:
            pad.close()
        receiver = inspect_receiver(require_manual_receipts=True)
    from .ros_transport import RosTransport
    from omi_hil_rl.training.eef_bc_grid import GridProfile
    gripper = GamepadGripper(args, calibration, args.execute) if args.execute else None
    transport = RosTransport(config, GridProfile(config.wrist_camera).CONTRACT, execute=args.execute,
        gamepad=args.gamepad, topic=receiver['manual_topic'] if receiver else '/omi/action/manual_decision',
        convention=config.sdk_convention, rgb_max_age_ms=args.rgb_max_age_ms,
        home_button_code=args.home_button_code, gripper=gripper)
    transport.competing_topics = ['/omi/action/decision', '/omi/action/manual_decision']
    transport.receiver_info = receiver
    transport.log_buttons = args.execute
    if not args.execute:
        try:
            transport.reset_history()
            obs, stamp = transport.observe(time.monotonic() + config.episode_seconds)
            print(json.dumps(dict(preview=True, observation_time_ns=stamp,
                                 shapes={k: list(v.shape) for k, v in obs.items()})))
        finally:
            transport.close()
        return
    if args.no_gripper:
        print('夹爪已禁用（--no-gripper），A/B不执行夹爪动作。', flush=True)
    try:
        gripper.start()
    except BaseException:
        transport.close()
        raise
    # One interrupt initiates orderly shutdown; repeated interrupts do not break saving.
    interrupted = False
    def stop(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        if args.control_mode == 'periodic':
            try:
                collect_periodic(args.output, config, transport, episodes=args.episodes, resume=args.resume)
            finally:
                transport.close()
        else:
            collect(args.output, config, transport, episodes=args.episodes, resume=args.resume)
    except KeyboardInterrupt:
        print('已停止；完整回合已保存，未完成回合仅保留审计、不入训练池。', flush=True)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
        gripper.close()


if __name__ == '__main__':
    main()
