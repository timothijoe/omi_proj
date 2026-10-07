"""Single-host, episode-alternating RL. Robot I/O stays in the parent process.

The learner is a bounded subprocess, never concurrent with an active episode.
This MVP deliberately refuses automatic recovery of an ambiguous training task.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np
import torch

from .collect_episodes import _collect
from .config import HILConfig
from .exchange import atomic_json, owner_lock, read_episode
from .networks import VERSION, load_actor
from .shutdown import interpreter_path


def wait_worker(command, log, tick, timeout=1800, stop=lambda: None):
    """Keep servicing RB while training. Child receives its own graceful SIGINT."""
    with Path(log).open('a') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        started = time.monotonic()
        try:
            while child.poll() is None:
                tick()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('learner deadline; see ' + str(log))
                time.sleep(.01)
            if child.returncode:
                raise RuntimeError(f'learner exited {child.returncode}; see {log}')
        finally:
            # Do not leave the last manual-reset command active while waiting
            # for a learner checkpoint on interrupt/failure.
            try:
                stop()
            except Exception:
                pass  # Still must reap the learner if ROS itself has failed.
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                # No more manual motion during shutdown; receiver deadman holds.
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    raise RuntimeError('learner killed after shutdown deadline; recovery needs inspection')


class Alternating:
    def __init__(self, run, config, transport, *, updates=10, batch_size=32,
                 device='cuda', learner_python=sys.executable, policy=False, timeout=1800):
        self.run, self.config, self.transport = Path(run), config, transport
        self.updates, self.batch_size, self.device = updates, batch_size, device
        self.learner_python, self.policy, self.timeout = learner_python, policy, timeout
        self.actor, self.version = None, None
        self.task = None

    def state(self, phase, **details):
        value = dict(phase=phase, policy_version=self.version, task=self.task, **details)
        atomic_json(self.run/'alternating_state.json', value)
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def idle(self):
        tick = getattr(self.transport, 'idle_tick', None)
        if tick:
            tick()

    def load(self, expected=None):
        self.state('LOADING')
        def work():
            actor, version, recipe = load_actor(self.run/'actor.pt', self.config.replay_contract(), self.device)
            if expected is not None and version != expected:
                raise ValueError(f'expected policy version {expected}, got {version}')
            # Warm CUDA kernels outside the active episode, and test finite outputs.
            index = json.loads((self.run/'dataset.json').read_text())['episodes']
            probe = next(read_episode(index[0]['path'], index[0]['manifest']))['observation']
            with torch.inference_mode():
                output = actor.sample({k: torch.as_tensor(v, device=self.device)[None]
                                       for k, v in probe.items()}, True)[0]
            if not torch.isfinite(output).all() or (output.abs() > 1).any():
                raise ValueError('loaded policy has invalid probe output')
            return actor, version
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            while not future.done():
                self.idle()
                time.sleep(.01)
            self.actor, self.version = future.result()
        self.transport.stop()
        # Any start press during save/train/load is consumed, never queued.
        if hasattr(self.transport, 'buttons'):
            self.transport.buttons.previous['start'] = True
        self.state('WAIT_START', policy_enabled=self.policy)

    def action(self, observation):
        # RB is independently checked again immediately before publishing.
        if getattr(self.transport, 'pad', None) and self.transport.pad.buttons.get(311, False):
            return np.zeros(6, np.float32)
        with torch.inference_mode():
            action = self.actor.sample({k: torch.as_tensor(v, device=self.device)[None]
                                        for k, v in observation.items()}, True)[0][0]
        return action.cpu().numpy()

    def finished(self, result):
        self.transport.stop()
        if not result['keep']:
            raise RuntimeError('episode invalid/discarded; paused for inspection: ' + str(result['reason']))
        self.task = dict(episode=result['episode'], base_version=self.version,
                         target_version=self.version + self.updates)
        self.state('TRAINING')
        self.actor = None
        if self.device == 'cuda':
            torch.cuda.empty_cache()
        command = [str(self.learner_python), '-m', 'omi_hil_rl.hil.learner',
                   '--run', str(self.run), '--config', str(self.run/'config.json'),
                   '--updates', str(self.updates), '--batch-size', str(self.batch_size),
                   '--device', self.device, '--wait-seconds', str(self.timeout),
                   '--alternating-episode', result['episode']]
        wait_worker(command, self.run/'learner.log', self.idle, self.timeout, self.transport.stop)
        self.load(expected=self.task['target_version'])
        atomic_json(self.run/'tasks'/f"{result['episode']}.json", dict(self.task, complete=True))
        self.task = None
        self.state('WAIT_START', policy_enabled=self.policy)

    def run_episodes(self, episodes):
        previous = self.run/'alternating_state.json'
        if previous.exists():
            state = json.loads(previous.read_text())
            if state['phase'] not in ('WAIT_START', 'CLOSED') or state.get('task'):
                raise ValueError('previous run is ambiguous/paused; inspect alternating_state.json before restarting')
        self.run.joinpath('tasks').mkdir(exist_ok=True)
        self.transport.allow_manual_reset = True
        results = []
        for ready in sorted(self.run.glob('episodes/*/ready.json')):
            result = json.loads(ready.read_text())
            if not (self.run/'tasks'/f"{result['episode']}.json").exists():
                raise ValueError('saved episode has no completed training task; inspect before restart')
            results.append(result)
        # A crashed partial episode is never a training input.
        for staging in self.run.glob('episodes/*/staging.json'):
            if not any((staging.parent/name).exists() for name in ('ready.json', 'discarded.json')):
                value = json.loads(staging.read_text())
                value.update(keep=False, reason='interrupted_unfinished_episode', episode_success=False,
                             count=len(list(staging.parent.glob('*.npz'))))
                atomic_json(staging.parent/'discarded.json', value)
        try:
            self.load()
            _collect(self.run, self.config, self.transport, episodes=episodes, results=results,
                     resume=True, action_provider=self.action if self.policy else None,
                     episode_finished=self.finished, policy_version=lambda: self.version,
                     close_transport=False, phase_hook=self.state)
            self.state('CLOSED')
        except KeyboardInterrupt:
            # Interrupted active prefixes are audit-only. Pending training needs inspection.
            self.state('PAUSED' if self.task else 'CLOSED', reason='operator_interrupt')
            raise
        except Exception as exc:
            self.state('PAUSED', reason=str(exc))
            raise


def make_transport(config, recipe, args):
    from .ros_transport import RosTransport
    from omi_hil_rl.real.receiver_preflight import inspect_receiver
    from omi_hil_rl.real.linux_gamepad import LinuxGamepad
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Float64MultiArray
    receiver = inspect_receiver(require_manual_receipts=True)
    pad = LinuxGamepad(args.gamepad)
    try:
        required = {config.start_button, config.success_button, config.stop_button}
        home_button_code = getattr(args, 'home_button_code', None)
        if home_button_code is not None:
            required.add(home_button_code)
        if getattr(args, 'gripper', None) is not None and args.gripper.args.gripper_server:
            from omi_hil_rl.real.gamepad_gripper import BTN_A, BTN_B
            required.update((BTN_A, BTN_B))
        if not pad.poll() or not required <= set(pad.button_map):
            raise ValueError('gamepad unavailable or episode/home/gripper buttons absent: ' + pad.error)
    finally:
        pad.close()

    class RoutedTransport(RosTransport):
        """Keep manual commands on the receiver's manual route, policy on policy route."""
        def _publish(self, action, command_id=None, **kwargs):
            for topic in self.owned:
                if self.node.count_publishers(topic) != 1:
                    raise RuntimeError('competing/missing publisher: ' + topic)
            for topic in {'/omi/action/manual_decision', '/omi/action/decision', receiver['manual_topic']} - set(self.owned):
                if self.node.count_publishers(topic):
                    raise RuntimeError('competing controller: ' + topic)
            old_topic, old_publisher = self.topic, self.publisher
            topic = receiver['manual_topic'] if not command_id or self.last_owner == 'human' else '/omi/action/decision'
            try:
                self.topic, self.publisher = topic, self.owned[topic]
                return super()._publish(action, command_id, **kwargs)
            finally:
                self.topic, self.publisher = old_topic, old_publisher

        def stop(self):
            if not hasattr(self, 'owned'):
                return
            # Both receiver paths must be stopped. No tagged training transition.
            from std_msgs.msg import Float64MultiArray
            if not getattr(self, '_closed', False) and self.rclpy.ok():
                for publisher in self.owned.values():
                    publisher.publish(Float64MultiArray(data=[0.] * 6))

        def close(self):
            if not getattr(self, '_closed', False):
                self.stop()
                self._closed = True
                super().close()

    transport = RoutedTransport(config, recipe['base_contract'], execute=True,
        gamepad=args.gamepad, convention=config.sdk_convention, rgb_max_age_ms=args.rgb_max_age_ms,
        home_button_code=getattr(args, 'home_button_code', None), gripper=getattr(args, 'gripper', None))
    manual_topic = receiver['manual_topic']
    if manual_topic == '/omi/action/decision':
        transport.close()
        raise ValueError('receiver manual and policy topics must be distinct')
    transport.owned = {transport.topic: transport.publisher,
        manual_topic: transport.node.create_publisher(Float64MultiArray, manual_topic,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))}
    transport.competing_topics = []  # Checked against BOTH owned endpoints above.
    transport.receiver_info = receiver
    transport.log_buttons = getattr(args, 'log_buttons', False)
    if transport.gripper is not None:
        try:
            transport.gripper.start()
        except BaseException:
            transport.close()
            raise
    return transport


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--prepare', action='store_true', help='initialize v2 from human data; no ROS/robot')
    p.add_argument('--source', type=Path, nargs='+', default=[Path('local/rl_episodes/collect_20261006_001958')])
    p.add_argument('--pretrained', type=Path, default=Path('local/pretrained/serl_resnet10/backbone.pt'))
    p.add_argument('--capacity', type=int, default=2000)
    p.add_argument('--updates', type=int, default=10)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    p.add_argument('--learner-python', type=Path, default=Path('local/cuda-env/bin/python'))
    p.add_argument('--episodes', type=int, default=100000)
    p.add_argument('--gamepad', default='/dev/input/js0')
    p.add_argument('--rgb-max-age-ms', type=float, default=500.)
    p.add_argument('--train-timeout', type=float, default=1800.)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--enable-policy', action='store_true', help='allow unvalidated RL policy motion when RB released')
    args = p.parse_args()
    if min(args.updates, args.batch_size, args.episodes, args.train_timeout) <= 0 or args.batch_size < 2:
        p.error('positive counts/timeouts and batch size >= 2 required')
    args.run = args.run.resolve()
    args.learner_python = interpreter_path(args.learner_python)
    torch.set_num_threads(2)
    if args.prepare:
        if args.execute or args.enable_policy:
            p.error('--prepare cannot execute robot actions')
        from .offline_train import train
        from .shutdown import graceful_stop
        with graceful_stop() as should_stop:
            train([s.resolve() for s in args.source], args.run, args.pretrained.resolve(),
                  updates=max(2, args.updates), batch_size=args.batch_size, device=args.device,
                  capacity=args.capacity, should_stop=should_stop)
        return
    if not args.execute:
        p.error('live collection requires --execute; use --prepare for offline initialization')
    config = HILConfig(**json.loads((args.run/'config.json').read_text()))
    if config.transport != 'ros' or config.review != 'auto':
        p.error('prepared ROS auto-review contract required')
    # Refuse old v1/BC weights rather than silently changing architecture or action scale.
    checkpoint = torch.load(args.run/'actor.pt', map_location='cpu', weights_only=True)
    if checkpoint['version'] != VERSION or checkpoint['contract'] != config.replay_contract():
        p.error('prepare a matching v2 RL checkpoint first')
    recipe = checkpoint['recipe']
    del checkpoint
    interrupted = False
    def interrupt(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with owner_lock(args.run, 'actor'):
            with owner_lock(args.run, 'learner'):
                pass  # Reject an already running learner before creating robot publishers.
            transport = make_transport(config, recipe, args)
            try:
                Alternating(args.run, config, transport, updates=args.updates, batch_size=args.batch_size,
                    device=args.device, learner_python=args.learner_python, policy=args.enable_policy,
                    timeout=args.train_timeout).run_episodes(args.episodes)
            except Exception as exc:
                if interrupted:
                    raise KeyboardInterrupt from exc
                transport.stop()
                transport.allow_manual_reset = True
                transport.reset_requires_release = True
                print(f'PAUSED: {exc}。模型已停；松开再按RB可人工复位；Ctrl+C退出。', flush=True)
                while True:
                    transport.idle_tick()
                    time.sleep(.01)
            finally:
                # _collect closes its transport; initialization failures also need cleanup.
                transport.close()
    except KeyboardInterrupt:
        print('已停止；完整回合在硬盘中，未完成回合不入池。检查 alternating_state.json。', flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
