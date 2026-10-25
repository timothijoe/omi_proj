"""Read-only RViz panels with isolated renderers and an independent arrival probe."""
from __future__ import annotations

import argparse
from collections import deque
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .grid_live_v2_core import (
    NS, MODEL_NS, STALE_NS, Arrival, diagnostics_image, header_stamp_cdr,
    panels, placeholder, held_roi, render_panel, source_topics,
)


def write_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
    temp.replace(path)


def ros_node(name):
    import rclpy
    rclpy.init()
    return rclpy.create_node(name)


def latest_qos():
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    return QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)


def close_node(node):
    import rclpy
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


def run_probe(args):
    import rclpy
    from sensor_msgs.msg import Image
    from geometry_msgs.msg import PoseStamped, WrenchStamped
    from std_msgs.msg import String
    from rclpy.executors import ExternalShutdownException
    node = ros_node('omi_live_v2_arrivals')
    items = panels(args.wrist_topic)
    sources = {topic: Arrival() for topic in source_topics(items)}
    outputs = {p.key: Arrival() for p in items if p.kind != 'direct'}
    outputs['control_bar'] = Arrival()
    workers = {}
    controls = {}
    unavailable = {}
    for topic, kind in source_topics(items).items():
        cls = dict(image=Image, pose=PoseStamped, wrench=WrenchStamped).get(kind)
        if kind == 'joints':
            try:
                from marvin_msgs.msg import Jointfeedback
                cls = Jointfeedback
            except ImportError:
                unavailable[topic] = 'marvin_msgs unavailable'
                continue
        def receive(data, key=topic):
            sources[key].receive(header_stamp_cdr(data), time.monotonic_ns())
        node.create_subscription(cls, topic, receive, latest_qos(), raw=True)
    for p in items:
        if p.kind == 'direct':
            continue
        node.create_subscription(Image, p.topic,
                                 lambda data, key=p.key: outputs[key].receive(header_stamp_cdr(data), time.monotonic_ns()),
                                 latest_qos(), raw=True)
        def worker_status(msg, key=p.key):
            try:
                value = json.loads(msg.data)
                if not isinstance(value, dict):
                    return
                # Heartbeat receive time is local; a stale or crashed worker is explicit.
                value['heartbeat_received_mono_ns'] = time.monotonic_ns()
                workers[key] = value
            except (ValueError, TypeError):
                pass
        node.create_subscription(String, p.topic+'/status', worker_status, 1)
    node.create_subscription(Image, NS+'/control_bar',
        lambda data: outputs['control_bar'].receive(header_stamp_cdr(data), time.monotonic_ns()), latest_qos(), raw=True)
    def control_status(msg):
        try:
            value = json.loads(msg.data)
            if not isinstance(value, dict) or value.get('schema') != 'omi-control-bar-v1':
                return
            controls.clear()
            controls.update(value, heartbeat_received_mono_ns=time.monotonic_ns())
        except (TypeError, ValueError):
            pass
    node.create_subscription(String, NS+'/control/status', control_status, 1)
    publisher = node.create_publisher(String, NS+'/status', 1)

    def tick():
        mono, wall = time.monotonic_ns(), node.get_clock().now().nanoseconds
        report = dict(schema='omi-live-panels-v2', pid=os.getpid(), emitted_mono_ns=mono,
                      sources={k: v.report(mono, wall) for k, v in sources.items()},
                      outputs={k: v.report(mono, wall) for k, v in outputs.items()},
                      workers=workers, control_bar=controls, unavailable=unavailable,
                      scope='Independent subscriber callback arrivals; no payload or hardware freshness validation')
        for topic, error in unavailable.items():
            report['sources'][topic].update(state='UNAVAILABLE', error=error)
        publisher.publish(String(data=json.dumps(report, allow_nan=False)))
    node.create_timer(.5, tick)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        close_node(node)


def run_panel(args):
    import rclpy
    import numpy as np
    from sensor_msgs.msg import Image
    from std_msgs.msg import String, Header
    from rclpy.executors import SingleThreadedExecutor, ExternalShutdownException
    from .tactile_live import image_message
    p = next(p for p in panels(args.wrist_topic) if p.key == args.panel and p.kind != 'direct')
    node = ros_node('omi_live_v2_'+p.key)
    publisher = node.create_publisher(Image, p.topic, latest_qos())
    telemetry = node.create_publisher(String, p.topic+'/status', 1)
    lock = threading.Lock()
    slot = dict(message=None, sequence=0, receive_ns=None, taken=0)
    status = dict(panel=p.key, pid=os.getpid(), state='WAITING', render_started_mono_ns=None,
                  publish_started_mono_ns=None, render_ms=None, render_max_ms=0.,
                  receive_to_publish_ms=None, published=0, skipped=0, error=None)
    render_history = deque(maxlen=128)

    def receive(msg):
        now = time.monotonic_ns()
        with lock:
            if slot['sequence'] > slot['taken']:
                status['skipped'] += 1
            slot.update(message=msg, sequence=slot['sequence']+1, receive_ns=now)
    node.create_subscription(Image, p.source, receive, latest_qos())

    def heartbeat():
        with lock:
            value = dict(status, received=slot['sequence'], emitted_mono_ns=time.monotonic_ns())
        telemetry.publish(String(data=json.dumps(value, allow_nan=False)))
    node.create_timer(.5, heartbeat)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_errors = []

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass
        except Exception as exc:
            spin_errors.append(exc)
    thread = threading.Thread(target=spin, daemon=True, name='panel-receiver')
    thread.start()
    last_token = None
    last_good = None
    last_good_rx = None
    try:
        while rclpy.ok() and not spin_errors:
            cycle = time.monotonic()
            with lock:
                msg, seq, rx = slot['message'], slot['sequence'], slot['receive_ns']
                slot['taken'] = seq
            now = time.monotonic_ns()
            state = 'WAITING' if msg is None else 'STALE' if now-rx > STALE_NS else 'OK'
            token = (seq, state) if state == 'OK' else (None, state)
            if state == 'STALE' and p.kind == 'roi' and last_good is not None:
                token = (None, state, now//500_000_000)
            if token != last_token:
                began = time.monotonic_ns()
                with lock:
                    status.update(render_started_mono_ns=began, state=state)
                error = None
                try:
                    if state == 'STALE' and p.kind == 'roi' and last_good is not None:
                        image = held_roi(last_good, (now-last_good_rx)/1e6)
                    else:
                        image = render_panel(p, msg) if state == 'OK' else placeholder(p.title, state)
                except Exception as exc:
                    state, error = 'BAD_DATA', f'{type(exc).__name__}: {exc}'[:300]
                    image = placeholder(p.title, state)
                render_end = time.monotonic_ns()
                # Do not publish an old result as OK after a slow renderer.
                if state == 'OK' and render_end-rx > STALE_NS:
                    state = 'STALE_RESULT'
                    image = held_roi(last_good, (render_end-last_good_rx)/1e6) if p.kind == 'roi' and last_good is not None else placeholder(p.title, state)
                elif state == 'OK' and p.kind == 'roi':
                    last_good, last_good_rx = image.copy(), rx
                header = msg.header if state == 'OK' else Header()
                if state != 'OK':
                    header.stamp = node.get_clock().now().to_msg()
                    header.frame_id = 'display_status_only'
                publish_start = time.monotonic_ns()
                render_ms = (render_end-began)/1e6
                render_history.append(render_ms)
                with lock:
                    status.update(render_started_mono_ns=None, publish_started_mono_ns=publish_start,
                                  render_ms=render_ms, render_max_ms=max(status['render_max_ms'], render_ms),
                                  render_p95_ms=float(np.percentile(render_history, 95)))
                publisher.publish(image_message(np.asarray(image), header, 'rgb8'))
                finished = time.monotonic_ns()
                with lock:
                    status.update(state=state, error=error, publish_started_mono_ns=None,
                                  publish_ms=(finished-publish_start)/1e6,
                                  receive_to_publish_ms=None if rx is None else (finished-rx)/1e6,
                                  source_stamp_ns=None if msg is None else msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,
                                  last_publish_mono_ns=finished, published=status['published']+1)
                last_token = token
            time.sleep(max(.001, 1/args.hz-(time.monotonic()-cycle)))
        if spin_errors:
            raise spin_errors[0]
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown(timeout_sec=2.)
        thread.join(timeout=2.)
        close_node(node)


def run_diagnostics(args):
    import rclpy
    import numpy as np
    from sensor_msgs.msg import Image
    from std_msgs.msg import String, Header
    from rclpy.executors import ExternalShutdownException
    from .tactile_live import image_message
    node = ros_node('omi_live_v2_diagnostics')
    current = dict(snapshot={}, received=None)
    items = panels(args.wrist_topic)
    def receive(msg):
        try:
            value = json.loads(msg.data)
            if value.get('schema') == 'omi-live-panels-v2':
                current.update(snapshot=value, received=time.monotonic_ns())
        except (ValueError, TypeError, AttributeError):
            pass
    node.create_subscription(String, NS+'/status', receive, 1)
    publisher = node.create_publisher(Image, NS+'/diagnostics', latest_qos())
    output = Path(args.output)
    def tick():
        mono = time.monotonic_ns()
        image = diagnostics_image(current['snapshot'], items, mono, current['received'])
        header = Header()
        header.stamp = node.get_clock().now().to_msg()
        header.frame_id = 'diagnostics_only'
        publisher.publish(image_message(np.asarray(image), header, 'rgb8'))
        # Only small JSON. No per-refresh PNG encoding/disk IO in image workers.
        try:
            write_json(output/'status.json', dict(current['snapshot'], diagnostics_mono_ns=mono,
                       probe_silent=current['received'] is None or mono-current['received'] > 2*10**9))
        except OSError as exc:
            node.get_logger().error(f'Diagnostics JSON write failed: {exc}')
    node.create_timer(.5, tick)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        close_node(node)


def rviz_config(root, args):
    import yaml
    config = yaml.safe_load((root/'scripts/grid_live_observation_v2.rviz').read_text())
    # RViz reuses the left-dock bool when the right-dock key is missing.
    # Also handle older templates that only explicitly hid Displays/Views.
    config['Window Geometry'].setdefault('Hide Right Dock', False)
    manager = config['Visualization Manager']
    if getattr(args, 'window_size', None):
        config['Window Geometry'].update(Width=args.window_size[0], Height=args.window_size[1])
    for display in manager['Displays']:
        if display['Name'] == 'Wrist image (see topic)':
            display['Topic']['Value'] = args.wrist_topic
        if display['Class'] == 'rviz_default_plugins/RobotModel':
            display['Enabled'] = display['Value'] = args.model_mode == 'corrected'
        if display['Class'] == 'rviz_default_plugins/MarkerArray':
            display['Enabled'] = display['Value'] = args.model_mode == 'corrected'
    return config


def supervise(commands, env, output, duration):
    """A failed field worker stays failed and visible; other panels keep running."""
    children, files, handlers = {}, [], {}
    stopped = threading.Event()
    start = time.monotonic()
    def stop(*_):
        stopped.set()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, stop)
        for role, command in commands.items():
            stream = (output/(role+'.log')).open('w')
            files.append(stream)
            children[role] = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        announced = set()
        while not stopped.wait(.2):
            states = {role: dict(pid=p.pid, returncode=p.poll()) for role, p in children.items()}
            write_json(output/'processes.json', states)
            for role, state in states.items():
                if state['returncode'] is not None and role not in announced:
                    announced.add(role)
                    print(f'{role} exited ({state["returncode"]}); see {output/(role+".log")}', flush=True)
                    if role in ('rviz', 'probe', 'diagnostics'):
                        return state['returncode'] or (0 if role == 'rviz' else 1)
            if duration is not None and time.monotonic()-start >= duration:
                break
        return 0
    finally:
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        for sig, timeout in ((signal.SIGINT, 5.), (signal.SIGTERM, 2.), (signal.SIGKILL, 2.)):
            for child in children.values():
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, sig)
                    except ProcessLookupError:
                        pass
            deadline = time.monotonic()+timeout
            for child in children.values():
                try:
                    child.wait(timeout=max(.01, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
            if all(p.poll() is not None for p in children.values()):
                break
        for stream in files:
            stream.close()
        try:
            write_json(output/'processes.json', {
                role: dict(pid=p.pid, returncode=p.poll(), checked_mono_ns=time.monotonic_ns())
                for role, p in children.items()})
        except OSError:
            pass
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hz', type=positive, default=10., help='maximum new-frame conversion Hz per derived panel; raw panels follow their topics')
    parser.add_argument('--model-hz', type=positive, default=30.)
    parser.add_argument('--domain', type=int, default=13)
    parser.add_argument('--model-mode', choices=('corrected', 'none'), default='corrected')
    parser.add_argument('--wrist-topic', default='/omi/wrist/color/image_roi', help='explicit image topic; no inferred full image or automatic fallback')
    parser.add_argument('--no-rviz', action='store_true')
    parser.add_argument('--duration', type=positive)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--window-size', type=int, nargs=2, metavar=('WIDTH', 'HEIGHT'), help='override initial RViz window size, e.g. 1800 1000')
    parser.add_argument('--manual-topic', default='auto', help='command display subscription; auto reads receiver parameters')
    parser.add_argument('--policy-topic', default='auto', help='command display subscription; auto reads receiver parameters')
    parser.add_argument('--receiver-node', default='/delta_ctrl_node', help='read-only parameter service for command routes')
    parser.add_argument('--command-translation-range-mm', type=positive, default=1.5, help='bar display range only, not a robot limit')
    parser.add_argument('--command-rotation-range-deg', type=positive, default=1., help='bar display range only, not a robot limit')
    parser.add_argument('--role', choices=('probe', 'panel', 'diagnostics', 'model', 'control'), help=argparse.SUPPRESS)
    parser.add_argument('--panel', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 0 <= args.domain <= 232 or args.hz > 30 or args.model_hz > 60:
        parser.error('domain must be 0..232, hz <=30, model-hz <=60')
    if args.window_size and min(args.window_size) < 400:
        parser.error('window dimensions must be at least 400')
    if not args.wrist_topic.startswith('/') or any(c.isspace() for c in args.wrist_topic):
        parser.error('wrist-topic must be an absolute ROS topic')
    for name in ('manual_topic', 'policy_topic', 'receiver_node'):
        value = getattr(args, name)
        if value == 'auto' and name != 'receiver_node':
            continue
        if not value.startswith('/') or any(c.isspace() for c in value):
            parser.error(name+' must be an absolute ROS name')
    if args.manual_topic != 'auto' and args.manual_topic == args.policy_topic:
        parser.error('manual and policy display topics must differ')
    if args.role:
        if args.role == 'probe':
            return run_probe(args)
        if args.role == 'panel':
            return run_panel(args)
        if args.role == 'diagnostics':
            return run_diagnostics(args)
        if args.role == 'control':
            from .grid_live_v2_control import run_control
            return run_control(args)
        # Reuse the v1 read-only model in THIS isolated process with v2 topics.
        from . import grid_live_review as legacy
        legacy.NS, legacy.MODEL_NS = NS, MODEL_NS
        return legacy.run_model_node(args)
    root = Path(os.environ.get('OMI_PROJECT_ROOT', Path(__file__).resolve().parents[3]))
    runtime = root/'local/grid_live_v2'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime/f'domain-{args.domain}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('v2 viewer already running in this domain')
        if args.output:
            args.output = args.output.resolve()
            args.output.mkdir(parents=True, exist_ok=False)
        else:
            args.output = Path(tempfile.mkdtemp(prefix='session-', dir=runtime))
        import yaml
        config = rviz_config(root, args)
        config_path = args.output/'live.rviz'
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        env = dict(os.environ, OMI_PROJECT_ROOT=str(root), ROS_DOMAIN_ID=str(args.domain),
                   ROS_LOCALHOST_ONLY='0', ROS_AUTOMATIC_DISCOVERY_RANGE='SUBNET',
                   FASTRTPS_DEFAULT_PROFILES_FILE=str(root/'ros2/omi_sensors/config/live_dashboard_network.xml'))
        prefix = [sys.executable, '-m', 'omi_hil_rl.real.grid_live_v2', '--domain', str(args.domain),
                  '--output', str(args.output), '--hz', str(args.hz), '--wrist-topic', args.wrist_topic]
        commands = {role: prefix+['--role', role] for role in ('probe', 'diagnostics')}
        commands['control'] = prefix+['--role', 'control', '--manual-topic', args.manual_topic,
            '--policy-topic', args.policy_topic, '--receiver-node', args.receiver_node,
            '--command-translation-range-mm', str(args.command_translation_range_mm),
            '--command-rotation-range-deg', str(args.command_rotation_range_deg)]
        for p in panels(args.wrist_topic):
            if p.kind != 'direct':
                commands[p.key] = prefix+['--role', 'panel', '--panel', p.key]
        remaps = ['--ros-args', '-r', '/tf:='+MODEL_NS+'/tf', '-r', '/tf_static:='+MODEL_NS+'/tf_static']
        if args.model_mode == 'corrected':
            from .wrist_recorded_review import prepare_model
            model = prepare_model(root/'local/models/omi_marvin_stand_axis_corrected_v1', args.output,
                                  root/'scripts/grid_live_observation.rviz')
            commands['model'] = prefix+['--role', 'model', '--model-hz', str(args.model_hz)]
            commands['robot_state_publisher'] = ['ros2', 'run', 'robot_state_publisher', 'robot_state_publisher',
                                                *remaps, '-r', '__ns:='+MODEL_NS, '--params-file', str(model/'publisher.yaml')]
        if not args.no_rviz:
            commands['rviz'] = ['rviz2', '-d', str(config_path), *remaps]
        write_json(args.output/'session.json', dict(schema='omi-live-panels-v2', commands=commands,
                   panels=[vars(p) for p in panels(args.wrist_topic)], domain=args.domain,
                   timing='local subscriber arrivals and renderer durations, not exposure or screen presentation',
                   raw_stale_behavior='RViz may retain last raw image; check independent RX diagnostics'))
        print(f'V2 independent panels | domain {args.domain} | {args.output}\nRaw images direct; derived panels <= {args.hz:g} Hz. Ctrl+C/close RViz to stop this viewer.', flush=True)
        return supervise(commands, env, args.output, args.duration)


if __name__ == '__main__':
    sys.exit(main())
