"""Fixed deterministic BC actor + human intervention + episodes; no learner."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import queue
import signal
import threading
import time

import torch

from .async_training import AsyncActor
from .alternating import make_transport
from .bc_wrench_monitor import BCWrenchMonitor
from .config import HILConfig
from .exchange import atomic_json, atomic_torch, owner_lock, read_episode
from .networks import VERSION, load_actor
from .periodic_control import _banner, run_periodic
from omi_hil_rl.training.eef_bc_data import sha256


def prepare(checkpoint, output, device='cpu'):
    checkpoint, output = Path(checkpoint).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('output already exists; use --resume or choose a new directory')
    state = torch.load(checkpoint, map_location='cpu', weights_only=True)
    if state.get('version') != VERSION or state.get('training_method') != 'behavior_cloning':
        raise ValueError('a v2 behavior_cloning actor checkpoint is required, not a SAC checkpoint')
    config = HILConfig(**state['contract']['config'])
    if config.replay_contract() != state['contract']:
        raise ValueError('BC config/contract mismatch')
    if any(not torch.isfinite(v).all() for v in state['actor'].values() if torch.is_floating_point(v)):
        raise ValueError('nonfinite BC weights')
    index = json.loads((checkpoint.parent/'dataset.json').read_text())
    if not index['episodes'] or any(e['manifest']['contract'] != state['contract'] for e in index['episodes']):
        raise ValueError('BC dataset/contract mismatch')
    # Verify loading and one recorded-observation inference BEFORE any ROS setup.
    actor, version, _ = load_actor(checkpoint, state['contract'], device)
    ep = index['episodes'][0]
    observation = next(read_episode(ep['path'], ep['manifest']))['observation']
    with torch.inference_mode():
        result = actor.sample({k: torch.as_tensor(v, device=device)[None]
                               for k, v in observation.items()}, True)[0]
    if not torch.isfinite(result).all() or (result.abs() > 1).any():
        raise ValueError('invalid BC probe output')
    output.mkdir(parents=True, exist_ok=False)
    atomic_torch(output/'actor.pt', state)
    atomic_json(output/'config.json', state['contract']['config'])
    atomic_json(output/'recipe.json', state['recipe'])
    atomic_json(output/'dataset.json', index)
    atomic_json(output/'bc_session.json', dict(mode='fixed_bc_eval_v1', stage='BC_EVAL',
        source_checkpoint=str(checkpoint), source_sha256=sha256(checkpoint),
        actor_sha256=sha256(output/'actor.pt'), policy_version=version,
        contract=state['contract'], learner_enabled=False, deterministic=True,
        reset_actions_in_replay=False))
    print(f'BC_PREPARED: {output}; version={version}; learner=OFF; robot publishers=0', flush=True)


def validate_run(run):
    session = json.loads((run/'bc_session.json').read_text())
    config = HILConfig(**json.loads((run/'config.json').read_text()))
    if (session['mode'] != 'fixed_bc_eval_v1' or session['learner_enabled'] or
            session['contract'] != config.replay_contract() or
            session['actor_sha256'] != sha256(run/'actor.pt')):
        raise ValueError('fixed BC session/checkpoint changed; refusing to execute')
    if (run/'learner.pt').exists() or (run/'async_session.json').exists():
        raise ValueError('cannot mix fixed BC collection and SAC training in one directory')
    return config


class FixedBCActor(AsyncActor):
    def close_wrench_logger(self):
        spin_stop = getattr(self, 'wrench_spin_stop', None)
        if spin_stop is not None:
            spin_stop.set()
            self.wrench_spin_thread.join(timeout=2.)
            self.wrench_executor.shutdown()
            self.wrench_node.destroy_node()
            self.wrench_spin_stop = None
        thread = getattr(self, 'wrench_warning_thread', None)
        if thread is not None:
            self.wrench_warning_queue.put(None)
            thread.join(timeout=2.)
            self.wrench_warning_thread = None

    def periodic_monitor_start(self, episode, started):
        monitor = getattr(self, 'wrench_monitor', None)
        if monitor is None:
            return
        try:
            with getattr(self, 'wrench_monitor_lock', nullcontext()):
                status = monitor.begin(episode, started)
            self.wrench_monitor_status = status
            print('BC_WRENCH_BASELINE: ' + json.dumps(status, ensure_ascii=False), flush=True)
            if status['status'] == 'monitoring':
                _banner('双指触觉基线已记录；本回合仅预警，不改变动作或成功标签', '36')
            else:
                _banner('双指触觉基线不可用：本回合不作阈值判断', '33')
        except Exception as exc:
            self.wrench_monitor_status = dict(episode=episode, status='monitor_error', reason=str(exc))
            print('BC_WRENCH_MONITOR_ERROR: ' + str(exc), flush=True)

    def periodic_monitor_end(self, episode):
        monitor = getattr(self, 'wrench_monitor', None)
        if monitor is None:
            return
        try:
            with getattr(self, 'wrench_monitor_lock', nullcontext()):
                result = monitor.finish(episode) or self.wrench_monitor_status
            atomic_json(self.run/'periodic_episodes'/episode/'wrench_monitor.json', result)
            print('BC_WRENCH_SUMMARY: ' + json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            print('BC_WRENCH_MONITOR_ERROR: ' + str(exc), flush=True)

    def state(self, phase, **details):
        value = dict(phase=phase, stage='BC_EVAL', policy_version=self.version,
                     complete_episodes=self.completed, learner_enabled=False,
                     policy_selection='fixed_bc_checkpoint', **details)
        atomic_json(self.run/'bc_state.json', value)
        print(json.dumps(value, ensure_ascii=False), flush=True)
        if getattr(self, 'periodic_status', False):
            self._periodic_status(phase, details)

    def _periodic_status(self, phase, details):
        if phase == 'WAIT_START':
            message = ('离开接口、夹持稳定后按 Start(315)；按住 RB 可人工接管'
                       if getattr(self, 'wrench_monitor', None) is not None else
                       '等待开始固定 BC 评估：按 Start(315)；按住 RB 可人工接管')
            _banner(message, '36')
        elif phase == 'ACTIVE':
            _banner('固定 BC 推理已开始：按 308 标记成功，按 307 提前结束', '36')
        elif phase == 'EPISODE_RECORDED':
            audit = details['audit']
            reason = audit['reason']
            if reason == 'success':
                message, color = '任务成功：已收到 308 成功按键', '32'
            elif reason == 'manual_stop':
                message, color = '任务未标记成功：已收到 307 提前结束按键', '33'
            elif reason == 'timeout':
                message, color = '任务未标记成功：已达到回合时限', '33'
            else:
                message, color = f'回合异常停止：{reason}', '31'
            _banner(message, color)
            _banner(f"评估审计已保存：周期指令 {audit['ticks']} 次，"
                    f"符合配对条件 {audit['matched_pairs']} 次，其他 {audit['invalid_pairs']} 次；非训练数据", '36')
        elif phase == 'PAUSED':
            _banner(f"固定 BC 评估已暂停：{details['reason']}", '31')

    def finished(self, result):
        if not result['keep']:
            raise RuntimeError('invalid BC episode paused: ' + str(result['reason']))
        self.completed += 1
        self.state('EPISODE_COMMITTED', episode=result['episode'])
        # Deliberately never reload weights, even after ten episodes.


def attach_wrench_monitor(actor, transport, args):
    from geometry_msgs.msg import WrenchStamped
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data

    actor.wrench_warning_queue = queue.SimpleQueue()
    def log_warnings():
        while True:
            event = actor.wrench_warning_queue.get()
            if event is None:
                return
            print('BC_WRENCH_WARNING: ' + json.dumps(event, ensure_ascii=False), flush=True)
            _banner(f"触觉差值预警：{event['side'].upper()} 指 Fx/Fy 差模 "
                    f"{event['force_xy']:.3f}，力矩差模 {event['torque']:.3f}", '33')
    actor.wrench_warning_thread = threading.Thread(
        target=log_warnings, name='bc-wrench-logger', daemon=True)
    actor.wrench_warning_thread.start()

    actor.wrench_monitor = BCWrenchMonitor(
        force_xy_limit=args.wrench_force_xy_warning,
        torque_limit=args.wrench_torque_warning, emit=actor.wrench_warning_queue.put)
    actor.wrench_monitor_lock = threading.Lock()
    actor.wrench_node = transport.rclpy.create_node(
        'omi_bc_wrench_monitor', enable_rosout=False, start_parameter_services=False)
    for side in ('a', 'b'):
        def receive_wrench(message, side=side):
            wrench = message.wrench
            with actor.wrench_monitor_lock:
                actor.wrench_monitor.ingest(side, (
                    wrench.force.x, wrench.force.y, wrench.force.z,
                    wrench.torque.x, wrench.torque.y, wrench.torque.z), time.monotonic())
        actor.wrench_node.create_subscription(
            WrenchStamped, f'/omi/tactile_grid24x16/{side}/wrench',
            receive_wrench, qos_profile_sensor_data)
    actor.wrench_executor = SingleThreadedExecutor(context=actor.wrench_node.context)
    actor.wrench_executor.add_node(actor.wrench_node)
    actor.wrench_spin_stop = threading.Event()
    def spin_wrench():
        while not actor.wrench_spin_stop.is_set() and transport.rclpy.ok():
            actor.wrench_executor.spin_once(timeout_sec=.05)
    actor.wrench_spin_thread = threading.Thread(
        target=spin_wrench, name='bc-wrench-subscription', daemon=True)
    actor.wrench_spin_thread.start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path,
        default=Path('local/rl_training/bc_20261007_20s_01/actor.pt'))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--prepare-only', action='store_true', help='verify/copy BC only; no ROS or robot connection')
    parser.add_argument('--resume', action='store_true', help='resume an existing fixed BC output directory')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--episodes', type=int, default=100000)
    parser.add_argument('--gamepad', default='/dev/input/js0')
    parser.add_argument('--rgb-max-age-ms', type=float, default=500.)
    parser.add_argument('--home-button-code', type=int, default=314)
    parser.add_argument('--log-buttons', action='store_true')
    parser.add_argument('--control-mode', choices=('periodic', 'receipt'), default='periodic',
                        help='periodic: 100ms publisher + independent audit; receipt: old synchronous transition collector')
    parser.add_argument('--wrench-warning', action='store_true',
                        help='opt in to read-only per-Start wrench delta warnings during periodic BC evaluation')
    parser.add_argument('--wrench-force-xy-warning', type=float, default=1.5,
                        help='provisional, read-only per-finger baseline-relative Fx/Fy norm warning')
    parser.add_argument('--wrench-torque-warning', type=float, default=0.4,
                        help='provisional, read-only per-finger baseline-relative torque norm warning')
    args = parser.parse_args()
    if args.episodes < 1 or not 0 < args.rgb_max_age_ms < float('inf'):
        parser.error('positive episode count and finite positive RGB age required')
    if any(not 0 < value < float('inf') for value in
           (args.wrench_force_xy_warning, args.wrench_torque_warning)):
        parser.error('wrench warning limits must be finite and positive')
    if args.wrench_warning and args.control_mode != 'periodic':
        parser.error('--wrench-warning requires --control-mode periodic')
    torch.set_num_threads(2)
    args.output = args.output.resolve()
    if not args.resume:
        prepare(args.checkpoint, args.output, args.device)
    config = validate_run(args.output)
    if args.prepare_only:
        return
    if config.transport != 'ros' or config.review != 'auto':
        parser.error('live execution requires ROS/auto-review contract')
    interrupted = False
    def interrupt(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    transport = actor = None
    failed = None
    try:
        with owner_lock(args.output, 'actor'):
            recipe = json.loads((args.output/'recipe.json').read_text())
            transport = make_transport(config, recipe, args)
            actor = FixedBCActor(args.output, config, transport, device=args.device, policy=True)
            actor.periodic_status = args.control_mode == 'periodic'
            if actor.periodic_status and args.wrench_warning:
                attach_wrench_monitor(actor, transport, args)
            print('FIXED_BC: learner=OFF; deterministic=ON; 315=start, RB=human, 308=success, 307=stop', flush=True)
            if (args.output/'overfit_evaluation.json').exists():
                print('OVERFIT_EVAL: training-set fit; generalization NOT validated; '+
                      (args.output/'overfit_evaluation.json').read_text(), flush=True)
            try:
                if args.control_mode == 'periodic':
                    run_periodic(actor, args.episodes)
                else:
                    actor.run_episodes(args.episodes)
            except KeyboardInterrupt:
                print('STOP_REQUESTED: stopping BC output and draining episode writer...', flush=True)
            except Exception as exc:
                if interrupted:
                    raise KeyboardInterrupt from exc
                failed = str(exc)
                transport.stop()
                actor.close_pipeline()
                actor.state('PAUSED', reason=failed)
                transport.reset_requires_release = True
                print('PAUSED: RB人工复位仍可用；Ctrl+C退出；没有Learner进程。', flush=True)
                while True:
                    transport.idle_tick()
                    time.sleep(.01)
    except KeyboardInterrupt:
        print('BC_STOP_REQUESTED', flush=True)
    finally:
        try:
            if transport is not None:
                transport.stop()
        finally:
            try:
                if actor is not None:
                    actor.close_pipeline()
            finally:
                try:
                    if actor is not None:
                        close_wrench_logger = getattr(actor, 'close_wrench_logger', None)
                        if close_wrench_logger is not None:
                            close_wrench_logger()
                finally:
                    try:
                        if transport is not None:
                            transport.close()
                    finally:
                        if actor is not None:
                            actor.state('CLOSED', error=failed)
                        for sig, handler in handlers.items():
                            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
