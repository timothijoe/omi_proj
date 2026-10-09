"""Concurrent Actor/Learner with policy refresh every N complete episodes.

The actor owns robot output; the learner only imports committed episodes and
updates disk replay/checkpoints. 'Latest validated' is not 'best performing'.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import numpy as np
import torch

from .alternating import Alternating, make_transport
from .collect_episodes import _collect
from .config import HILConfig
from .exchange import atomic_json, owner_lock, read_episode, sync_directory
from .networks import VERSION, load_actor
from .shutdown import interpreter_path
from .policy_pipeline import LatestPolicy
from .ros_transport import RosTransport


def initialize(source, destination):
    """Clone a stopped offline seed, never hardlink mutable replay/checkpoints."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError('use a new destination outside the seed directory')
    if not source.is_dir():
        raise ValueError('seed directory missing')
    with owner_lock(source, 'actor'), owner_lock(source, 'learner'):
        if (source/'import_pending.json').exists() or list(source.glob('episodes/*/ready.json')):
            raise ValueError('initialize from an offline prepared seed, not a live collection run')
        manifest = json.loads((source/'replay/manifest.json').read_text())
        if not manifest['clean']:
            raise ValueError('seed replay is dirty; inspect/recover it first')
        checkpoint = torch.load(source/'learner.pt', map_location='cpu', weights_only=True)
        actor = torch.load(source/'actor.pt', map_location='cpu', weights_only=True)
        config = HILConfig(**json.loads((source/'config.json').read_text()))
        if (checkpoint['version'] != VERSION or actor['version'] != VERSION or
                checkpoint['contract'] != config.replay_contract() or actor['contract'] != checkpoint['contract'] or
                checkpoint['updates'] != actor['updates'] or checkpoint['recipe'] != actor['recipe']):
            raise ValueError('seed learner/actor/config mismatch; matching v2 checkpoints required')
        del checkpoint, actor
        required = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination.parent).free < required + 2_000_000_000:
            raise RuntimeError('insufficient free disk space for an independent replay copy')
        destination.mkdir()
        atomic_json(destination/'initializing.json', dict(source=str(source)))
        def copy_file(src, dst):
            shutil.copy2(src, dst)
            with open(dst, 'rb') as stream:
                os.fsync(stream.fileno())
            return dst
        for name in ('learner.pt', 'actor.pt', 'config.json', 'recipe.json', 'dataset.json'):
            copy_file(source/name, destination/name)
        shutil.copytree(source/'replay', destination/'replay', copy_function=copy_file)
        sync_directory(destination/'replay')
        extra = {}
        if (source/'async_session.json').exists():
            old_session = json.loads((source/'async_session.json').read_text())
            extra = {k: old_session[k] for k in ('control_mode', 'replay_backend', 'intervention_capacity') if k in old_session}
        atomic_json(destination/'async_session.json', dict(mode='async_hil_v1', seed=str(source),
                    contract=config.replay_contract(), reset_actions_in_replay=False,
                    policy_selection='latest_validated_not_best', replay_capacity=manifest['capacity'], **extra))
        print(f'PREPARED: {destination}; no robot publishers created', flush=True)


class LearnerProcess:
    """Child lifetime belongs to the supervisor, including Ctrl+C and exceptions."""
    def __init__(self, command, log):
        self.command, self.log = command, Path(log)
        self.child = None
        self.stream = None

    def start(self):
        self.stream = self.log.open('a')
        try:
            self.child = subprocess.Popen(self.command, stdout=self.stream, stderr=subprocess.STDOUT,
                                          start_new_session=True)
        except BaseException:
            self.stream.close()
            raise

    def check(self):
        if self.child is not None and self.child.poll() is not None:
            raise RuntimeError(f'learner exited {self.child.returncode}; see {self.log}')

    def close(self, timeout=30.):
        killed = False
        try:
            if self.child is not None and self.child.poll() is None:
                self.child.send_signal(signal.SIGINT)
                try:
                    self.child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait()
                    killed = True
                    print('LEARNER_KILLED: shutdown deadline; inspect checkpoint/replay before restart', flush=True)
        finally:
            if self.stream is not None:
                self.stream.close()
        return killed


class AsyncActor(Alternating):
    """Reuse action inference, but never wait for a learner training budget."""
    def __init__(self, run, config, transport, *, reload_episodes=10, device='cuda', policy=False):
        super().__init__(run, config, transport, device=device, policy=policy)
        if reload_episodes < 1:
            raise ValueError('reload interval must be positive')
        self.reload_episodes = reload_episodes
        self.completed = 0
        self.last_reload_check = 0
        self.recipe = None
        self.last_reload_error = None
        self.pipeline = None

    def close_pipeline(self):
        self.transport.policy_pipeline = None
        if self.pipeline is not None:
            self.pipeline.close()
            self.pipeline = None

    def action(self, observation):
        if self.pipeline is None:
            return super().action(observation)
        if self.transport.pad.buttons.get(311, False):
            return np.zeros(6, np.float32)
        latest = self.transport.latest
        if latest is None or latest[0] is not observation:
            raise RuntimeError('policy observation/candidate identity mismatch')
        candidate = self.pipeline.get(latest[1])
        if candidate is None:
            raise RuntimeError('no matching precomputed policy candidate')
        return candidate[0]

    def state(self, phase, **details):
        details.setdefault('arbitration_mode', getattr(self.transport, 'arbitration_mode', 'immediate'))
        value = dict(phase=phase, policy_version=self.version, complete_episodes=self.completed,
                     last_reload_check=self.last_reload_check, reload_episodes=self.reload_episodes,
                     policy_enabled=self.policy, policy_selection='latest_validated_not_best', **details)
        atomic_json(self.run/'async_state.json', value)
        monitor = getattr(self, 'telemetry', None)
        if monitor is not None:
            monitor.update(**value)
            monitor.event('actor_phase', phase=phase, policy_version=self.version,
                          episode=details.get('episode'))
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def load(self, expected=None):
        self.transport.stop()
        self.close_pipeline()
        self.transport.reset_requires_release = True
        self.state('LOADING')
        self.last_reload_error = None
        def work():
            # Atomic actor.pt replacement means this open sees a complete old OR new file.
            actor, version, recipe = load_actor(self.run/'actor.pt', self.config.replay_contract(), self.device)
            if self.recipe is not None and recipe != self.recipe:
                raise ValueError('policy recipe/normalization changed')
            if self.version is not None and version <= self.version:
                return None
            index = json.loads((self.run/'dataset.json').read_text())['episodes']
            probe = next(read_episode(index[0]['path'], index[0]['manifest']))['observation']
            with torch.inference_mode():
                output = actor.sample({k: torch.as_tensor(v, device=self.device)[None]
                                       for k, v in probe.items()}, True)[0]
            if not torch.isfinite(output).all() or (output.abs() > 1).any():
                raise ValueError('nonfinite/out-of-bounds policy probe')
            return actor, version, recipe
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            while not future.done():
                self.idle()  # RB stays usable during checkpoint I/O and GPU warmup.
                time.sleep(.01)
            try:
                candidate = future.result()
            except Exception as exc:
                if self.actor is None:
                    raise
                self.last_reload_error = repr(exc)
                print(f'RELOAD_REJECTED: keeping version {self.version}: {exc}', flush=True)
                candidate = None
            if candidate is not None:
                self.actor, self.version, self.recipe = candidate
                print(f'POLICY_LOADED: version={self.version}', flush=True)
            elif self.last_reload_error is None:
                print(f'NO_NEW_POLICY: keeping version={self.version}', flush=True)
        self.transport.stop()
        if hasattr(self.transport, 'buttons'):
            self.transport.buttons.previous['start'] = True
        self.last_reload_check = self.completed
        if self.policy and isinstance(self.transport, RosTransport):
            # Capture the fixed per-episode actor; worker never reads the pad or ROS.
            actor = self.actor
            def infer(observation):
                with torch.inference_mode():
                    return actor.sample({k: torch.as_tensor(v, device=self.device)[None]
                                         for k, v in observation.items()}, True)[0][0].cpu().numpy()
            self.pipeline = LatestPolicy(infer, consume_results=getattr(self.transport, 'observation_driven', False))
            self.transport.policy_pipeline = self.pipeline
            print('POLICY_PIPELINE: background inference; exact-observation candidates; '+
                  ('send on completion; timing diagnostic only' if getattr(self.transport, 'observation_driven', False)
                   else '100ms send gate retained'), flush=True)
        self.state('WAIT_START', reload_error=self.last_reload_error)

    def finished(self, result):
        if not result['keep']:
            raise RuntimeError('invalid episode paused: ' + str(result['reason']))
        self.completed += 1
        self.state('EPISODE_COMMITTED', episode=result['episode'])
        # No learner wait: committed ready.json is imported independently.
        if self.completed - self.last_reload_check >= self.reload_episodes:
            self.load()

    def run_episodes(self, episodes):
        session_path = self.run/'async_session.json'
        if session_path.exists() and json.loads(session_path.read_text()).get('control_mode') == 'periodic_training_v1':
            from .periodic_control import run_periodic
            if not hasattr(self.transport, 'arbitration_mode'):
                self.transport.arbitration_mode = 'after-inference'
            self.completed = sum(bool(json.loads(p.read_text()).get('training_ready'))
                                 for p in self.run.glob('periodic_episodes/*/audit.json'))
            return run_periodic(self, episodes, training=True)
        results = []
        for staging in sorted(self.run.glob('episodes/*/staging.json')):
            ready, discarded = staging.parent/'ready.json', staging.parent/'discarded.json'
            if not ready.exists() and not discarded.exists():
                value = json.loads(staging.read_text())
                value.update(keep=False, reason='process_interrupted_unfinished_episode',
                             episode_success=False, count=len(list(staging.parent.glob('*.npz'))))
                atomic_json(discarded, value)
            results.append(json.loads((ready if ready.exists() else discarded).read_text()))
        self.completed = sum(bool(r['keep']) for r in results)
        self.transport.allow_manual_reset = True
        self.load()  # Restart always loads newest valid weights and waits for a fresh 315 press.
        try:
            return _collect(self.run, self.config, self.transport, episodes=episodes, results=results,
                resume=True, action_provider=self.action if self.policy else None,
                episode_finished=self.finished, policy_version=lambda: self.version,
                close_transport=False, phase_hook=self.state)
        finally:
            self.transport.stop()
            self.close_pipeline()


def concurrency_probe(run, config, command, device):
    """Real observation inference + bounded learner, without importing/initializing ROS."""
    actor, version, _ = load_actor(run/'actor.pt', config.replay_contract(), device)
    index = json.loads((run/'dataset.json').read_text())['episodes']
    probe = next(read_episode(index[0]['path'], index[0]['manifest']))['observation']
    obs = {k: torch.as_tensor(v, device=device)[None] for k, v in probe.items()}
    def infer():
        with torch.inference_mode():
            output = actor.sample(obs, True)[0]
        if device == 'cuda':
            torch.cuda.synchronize()
        if not torch.isfinite(output).all():
            raise ValueError('nonfinite probe inference')
    for _ in range(3):
        infer()
    worker = LearnerProcess(command, run/'learner_probe.log')
    durations = []
    started = time.monotonic()
    worker.start()
    try:
        while worker.child.poll() is None:
            before = time.monotonic()
            infer()
            durations.append((time.monotonic()-before)*1000)
            if time.monotonic()-started > 180:
                raise TimeoutError('concurrency probe deadline')
            time.sleep(max(0., .1-(time.monotonic()-before)))
        if worker.child.returncode:
            raise RuntimeError('probe learner failed; see learner_probe.log')
    finally:
        worker.close()
    checkpoint = torch.load(run/'actor.pt', map_location='cpu', weights_only=True)
    if checkpoint['updates'] <= version:
        raise ValueError('probe learner did not advance')
    report = dict(robot_publishers_created=0, observation_source='recorded_seed',
        inference_samples=len(durations), initial_policy_version=version,
        latest_policy_version=checkpoint['updates'],
        inference_ms=dict(zip(('min','p50','p95','max'), np.percentile(durations, [0,50,95,100]).tolist())),
        inference_over_100ms=sum(d > 100 for d in durations),
        not_live_ros_latency_validation=True, not_policy_quality_validation=True)
    atomic_json(run/'concurrency_probe.json', report)
    print(json.dumps(report, indent=2), flush=True)
    return report


def main():
    from omi_hil_rl.real.gamepad_gripper import (
        BTN_A, BTN_B, add_gripper_arguments, calibration_from_args, GamepadGripper)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--initialize-from', type=Path, help='copy a stopped offline v2 seed; no robot connection')
    p.add_argument('--probe-only', action='store_true', help='recorded-observation concurrent inference/training; NO robot output')
    p.add_argument('--probe-updates', type=int, default=20)
    p.add_argument('--reload-every-episodes', type=int, default=10)
    p.add_argument('--publish-every', type=int, default=50, help='learner critic updates per weight publication')
    p.add_argument('--min-online', type=int, default=100)
    p.add_argument('--min-demo', type=int, default=1)
    p.add_argument('--batch-size', type=int, default=2)
    p.add_argument('--actor-device', choices=['cpu', 'cuda'], default='cuda')
    p.add_argument('--learner-device', choices=['cpu', 'cuda'], default='cuda')
    p.add_argument('--learner-python', type=Path, default=Path('local/cuda-env/bin/python'))
    p.add_argument('--learner-update-delay', type=float, default=0.)
    p.add_argument('--shutdown-timeout', type=float, default=30.)
    p.add_argument('--episodes', type=int, default=100000)
    p.add_argument('--gamepad', default='/dev/input/js0')
    p.add_argument('--home-button-code', type=int, default=314,
                   help='Back key for automatic home between episodes (default: 314)')
    add_gripper_arguments(p)
    project_root = Path(__file__).resolve().parents[3]
    p.set_defaults(
        gripper_server='192.168.14.11:55551',
        gripper_sdk_root=project_root / 'local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py',
        gripper_calibration=project_root / 'tutorials/gripper_limits.json')
    p.add_argument('--no-gripper', action='store_true', help='Disable A/B gripper control')
    p.add_argument('--rgb-max-age-ms', type=float, default=500.)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--enable-policy', action='store_true')
    p.add_argument('--arbitration-mode', choices=('after-inference', 'immediate'), default='after-inference',
                   help='periodic RL: choose latest RB/joystick after inference (default); immediate retains interrupting takeover')
    args = p.parse_args()
    if min(args.reload_every_episodes, args.publish_every, args.min_online, args.min_demo,
           args.batch_size, args.episodes, args.shutdown_timeout, args.probe_updates) <= 0 or args.batch_size < 2:
        p.error('positive counts required; batch-size >= 2')
    if not 0 <= args.learner_update_delay < float('inf') or not args.shutdown_timeout < float('inf'):
        p.error('delays must be finite and nonnegative')
    args.run = args.run.resolve()
    torch.set_num_threads(2)
    if args.initialize_from:
        if args.execute or args.enable_policy or args.probe_only:
            p.error('initialization is offline only')
        initialize(args.initialize_from, args.run)
        return
    if args.probe_only and (args.execute or args.enable_policy):
        p.error('probe cannot enable robot execution')
    if not args.execute and not args.probe_only:
        p.error('use --execute for live collection; --initialize-from only prepares disk data')
    session = json.loads((args.run/'async_session.json').read_text())
    config = HILConfig(**json.loads((args.run/'config.json').read_text()))
    if (session.get('mode') != 'async_hil_v1' or session['contract'] != config.replay_contract() or
            config.transport != 'ros' or config.review != 'auto'):
        p.error('matching ROS auto-review async session required')
    if (args.execute and args.enable_policy and args.arbitration_mode == 'after-inference' and
            session.get('control_mode') != 'periodic_training_v1'):
        p.error('after-inference requires a periodic_training_v1 session; use --arbitration-mode immediate for legacy receipt sessions')
    if args.execute:
        episode_buttons = (config.start_button, config.success_button, config.stop_button,
                           config.keep_button, config.discard_button, 311)
        if args.home_button_code < 0 or args.home_button_code in episode_buttons:
            p.error('home button must be distinct from episode buttons and RB')
        if args.no_gripper:
            args.gripper_server = None
            print('夹爪已禁用（--no-gripper），A/B不执行夹爪动作。', flush=True)
        if args.gripper_server and {BTN_A, BTN_B} & {config.start_button, config.success_button, config.stop_button}:
            p.error('A/B gripper buttons must be distinct from episode start/success/stop')
        calibration = calibration_from_args(args, p)
        args.gripper = GamepadGripper(args, calibration, True)
        args.log_buttons = True
    if (args.run/'alternating_state.json').exists():
        p.error('cannot mix asynchronous and alternating schedulers in one directory')
    checkpoint = torch.load(args.run/'actor.pt', map_location='cpu', weights_only=True)
    if checkpoint['version'] != VERSION or checkpoint['contract'] != config.replay_contract():
        p.error('matching v2 checkpoint required')
    recipe = checkpoint['recipe']
    del checkpoint
    # Do not resolve the venv's python symlink into /usr/bin/python: that loses
    # pyvenv.cfg and all project/CUDA dependencies in the child process.
    command = [interpreter_path(args.learner_python), '-m', 'omi_hil_rl.hil.learner',
        '--run', str(args.run), '--config', str(args.run/'config.json'),
        '--device', args.learner_device, '--batch-size', str(args.batch_size),
        '--min-online', str(args.min_online), '--min-demo', str(args.min_demo),
        '--publish-every', str(args.publish_every), '--update-delay', str(args.learner_update_delay)]
    if args.probe_only:
        with owner_lock(args.run, 'actor'):
            concurrency_probe(args.run, config, command + ['--updates', str(args.probe_updates)], args.actor_device)
        return
    interrupted = False
    def interrupt(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    worker = LearnerProcess(command, args.run/'learner.log')
    transport, actor = None, None
    failed, killed = None, False
    try:
        from .telemetry import TelemetryWriter
        with owner_lock(args.run, 'actor'), TelemetryWriter(args.run, 'actor') as telemetry:
            # Fail before robot publishers if a different learner owns this directory.
            with owner_lock(args.run, 'learner'):
                pass
            transport = make_transport(config, recipe, args)
            transport.arbitration_mode = args.arbitration_mode if args.enable_policy else 'immediate'
            actor = AsyncActor(args.run, config, transport, reload_episodes=args.reload_every_episodes,
                               device=args.actor_device, policy=args.enable_policy)
            actor.telemetry = transport.telemetry = telemetry
            telemetry.update(policy_enabled=args.enable_policy, execute=bool(args.execute),
                             arbitration_mode=transport.arbitration_mode)
            try:
                worker.start()
                transport.health_check = worker.check
                actor.run_episodes(args.episodes)
            except KeyboardInterrupt:
                print('STOP_REQUESTED: stopping robot output, writer and learner...', flush=True)
            except Exception as exc:
                if interrupted:
                    raise KeyboardInterrupt from exc
                failed = str(exc)
                transport.stop()
                actor.state('PAUSED', reason=failed)
                # A training fault must not silently leave autonomous collection running.
                killed = worker.close(args.shutdown_timeout)
                transport.health_check = None
                transport.reset_requires_release = True
                gripper_hint = '、A/B夹爪' if args.gripper_server else ''
                print('PAUSED: RB人工复位、Back回home' + gripper_hint + '仍可用；Ctrl+C关闭整个本次会话。', flush=True)
                while True:
                    transport.idle_tick()
                    time.sleep(.01)
            finally:
                try:
                    transport.stop()
                finally:
                    try:
                        killed = worker.close(args.shutdown_timeout) or killed
                    finally:
                        transport.close()
                actor.state('CLOSED', error=failed, learner_forced_kill=killed)
    except KeyboardInterrupt:
        print('CLOSED: 本次Actor/手柄读取/记录器/Learner已退出；独立传感器与接收端未关闭。', flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
