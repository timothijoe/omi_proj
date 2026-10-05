"""Real tactile and wrist acquisition groups, isolated from bag playback."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

from .cli import supervise, environment
from .config import load_config
from .wrist_image import TOPICS, LABELS
from .tactile_grid import MODES, topic_root


def transport_environment(config, root, transport):
    env = environment(config)
    discovery = 'SUBNET' if transport == 'network' else 'LOCALHOST'
    env.update(OMI_SENSOR_DISCOVERY_RANGE=discovery,
               ROS_LOCALHOST_ONLY='0' if transport == 'network' else '1',
               ROS_AUTOMATIC_DISCOVERY_RANGE=discovery)
    if transport == 'network':
        # Do not inherit a same-host XML profile into an explicitly networked run.
        env.pop('FASTRTPS_DEFAULT_PROFILES_FILE', None)
        env.pop('FASTDDS_DEFAULT_PROFILES_FILE', None)
    if transport == 'local-shm':
        env.pop('ROS_LOCALHOST_ONLY', None)
        env.update(RMW_IMPLEMENTATION='rmw_fastrtps_cpp',
                   FASTRTPS_DEFAULT_PROFILES_FILE=str(root/'ros2/omi_sensors/config/large_image_shm.xml'),
                   RMW_FASTRTPS_PUBLICATION_MODE='SYNCHRONOUS',
                   ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', nargs='?', choices=['all', 'tactile', 'camera', 'view'], default='all')
    parser.add_argument('--host', default='192.168.14.11')
    parser.add_argument('--pc-host', help='default: local IPv4 selected by route to host')
    parser.add_argument('--domain', type=int, default=os.environ.get('ROS_DOMAIN_ID', '88'),
                        help='ROS domain: --domain overrides ROS_DOMAIN_ID; fallback 88')
    parser.add_argument('--no-rviz', action='store_true')
    parser.add_argument('--duration', type=float, help='bounded test in seconds')
    parser.add_argument('--camera-fps', type=int, default=30)
    parser.add_argument('--camera-buffer', choices=['latest', 'record'], default='record',
                        help='record: bounded FIFO plus reliable /record topic; latest: low-latency only')
    parser.add_argument('--camera-buffer-frames', type=int, default=60)
    parser.add_argument('--camera-buffer-mib', type=int, default=64)
    parser.add_argument('--image-mode', choices=['full', 'roi'], default='full',
                        help='publish original BGR image or policy-compatible 128x128 ROI')
    parser.add_argument('--sdk-root', type=Path)
    parser.add_argument('--publish-raw', action='store_true',
                        help='grid mode: additionally publish original raw images on /omi/tactile/{a,b}/raw')
    parser.add_argument('--tactile-depth', action=argparse.BooleanOptionalAction, default=None,
                        help='enable SDK tactile depth and depth topics (not RealSense depth)')
    parser.add_argument('--tactile-wrench', action=argparse.BooleanOptionalAction, default=None,
                        help='enable SDK six-axis force/torque; unframed values labeled unsynchronized in metadata')
    parser.add_argument('--tactile-mode', choices=MODES, default=None,
                        help='default: tactile uses grid24x16 with depth; wrench/raw opt in; all/view keep legacy full')
    parser.add_argument('--plan', action='store_true', help='print commands without opening devices')
    parser.add_argument('--transport', choices=['default', 'local-shm', 'network'], default='default',
                        help='default/local-shm: same host; network: subnet discovery with default DDS profiles')
    args = parser.parse_args()
    if args.tactile_mode is None:
        args.tactile_mode = 'grid24x16' if args.component == 'tactile' else 'full'
    if args.tactile_depth is None:
        args.tactile_depth = args.tactile_mode == 'grid24x16'
    if args.tactile_wrench is None:
        args.tactile_wrench = False
    if args.publish_raw and args.component not in ('all', 'tactile'):
        parser.error('--publish-raw requires tactile or all')
    if (args.tactile_depth or args.tactile_wrench) and args.component == 'camera':
        parser.error('tactile depth/wrench flags apply to tactile/all/view, not wrist camera')
    if args.tactile_mode != 'full' and args.component != 'tactile':
        parser.error('grid24x16 currently requires component tactile; legacy dashboard needs full fields/images')
    ipaddress.IPv4Address(args.host)
    if not 0 <= args.domain <= 232 or min(args.camera_fps, args.camera_buffer_frames, args.camera_buffer_mib) <= 0 or (args.duration is not None and args.duration <= 0):
        parser.error('invalid domain/fps/duration')
    if not args.pc_host:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((args.host, 50088)); args.pc_host = probe.getsockname()[0]
    ipaddress.IPv4Address(args.pc_host)
    root = Path(os.environ['OMI_PROJECT_ROOT'])
    runtime = root/'local'/'daimon_live'; runtime.mkdir(parents=True, exist_ok=True)
    # Guard across domains too: hardware cannot safely be acquired twice.
    locks = []
    try:
        for component in (['tactile', 'camera', 'view'] if args.component == 'all' else [args.component]):
            if args.plan: continue
            if component == 'view' and args.no_rviz: continue
            file = (runtime/(args.host+'-'+component+'.lock')).open('a')
            locks.append(file)
            try: fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError(component+' already running through this launcher')
        with tempfile.TemporaryDirectory(prefix='session-', dir=runtime) as temp:
            config = json.loads((root/'ros2/omi_sensors/config/sdk_dashboard.example.json').read_text())
            config['domain_id'] = args.domain; config['realsense']['enabled'] = False
            config['tactile'].update(host=args.host, pc_host=args.pc_host,
                sdk_root=str((args.sdk_root or root/'local/vendor/daimon_tactile').resolve()))
            config['tactile']['enable_depth'] = args.tactile_depth
            config['tactile']['enable_wrench'] = args.tactile_wrench
            path = Path(temp)/'sensors.json'; path.write_text(json.dumps(config, indent=2))
            config = load_config(path)
            base = [sys.executable, '-m', 'omi_sensors.cli', '--config', str(path)]
            commands = []
            if args.component in ('all', 'tactile'):
                mode_args = [] if args.tactile_mode == 'full' else ['--tactile-mode', args.tactile_mode]
                if args.publish_raw:
                    mode_args += ['--publish-raw']
                commands.append(base+['live', *mode_args])
            if args.component in ('all', 'camera'):
                commands.append([sys.executable, '-m', 'omi_sensors.wrist_live', '--host', args.host,
                    '--pc-host', args.pc_host, '--fps', str(args.camera_fps), '--image-mode', args.image_mode,
                    '--buffer-mode', args.camera_buffer, '--buffer-frames', str(args.camera_buffer_frames),
                    '--buffer-mib', str(args.camera_buffer_mib)])
            if args.component in ('all', 'view') and not args.no_rviz:
                import yaml
                rviz = yaml.safe_load((root/'ros2/omi_sensors/config/daimon_live.rviz').read_text())
                wrist = rviz['Visualization Manager']['Displays'][0]
                wrist['Name'] = LABELS[args.image_mode]
                wrist['Topic']['Value'] = TOPICS[args.image_mode]
                rviz_path = Path(temp)/'live.rviz'
                rviz_path.write_text(yaml.safe_dump(rviz, sort_keys=False))
                commands += [base+['dashboard', '--rate', '15'],
                    ['rviz2', '-d', str(rviz_path)]]
            if not commands: parser.error('no processes requested')
            child_env = transport_environment(config, root, args.transport)
            if args.plan:
                print(json.dumps({'commands': commands, 'config': config, 'transport': args.transport,
                                  'environment': {k: child_env[k] for k in (
                                      'ROS_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'ROS_AUTOMATIC_DISCOVERY_RANGE',
                                      'OMI_SENSOR_DISCOVERY_RANGE') if k in child_env},
                                  'image_mode': args.image_mode, 'image_topic': TOPICS[args.image_mode],
                                  'tactile_mode': args.tactile_mode, 'publish_raw': args.publish_raw or args.tactile_mode == 'full',
                                  'tactile_topic_root': topic_root(args.tactile_mode)}, indent=2))
                return 0
            print('REAL hardware %s -> %s | ROS domain %s | %s | NO MOTION / NO RECORDING' %
                  (args.host,args.pc_host,args.domain,args.component), flush=True)
            print(LABELS[args.image_mode] + ' -> ' + TOPICS[args.image_mode], flush=True)
            print('ROS transport: %s | discovery: %s' %
                  (args.transport, child_env['ROS_AUTOMATIC_DISCOVERY_RANGE']), flush=True)
            if args.component in ('all', 'tactile'):
                print('Tactile ' + args.tactile_mode + ' -> ' + topic_root(args.tactile_mode), flush=True)
                print('Depth: %s | Wrench: %s (unframed SDK force explicitly unsynchronized)' %
                      (args.tactile_depth, args.tactile_wrench), flush=True)
            # SDK writes logs relative to cwd; keep them under ignored local/.
            os.chdir(runtime)
            return supervise(commands, child_env, args.duration)
    finally:
        for file in locks: file.close()


if __name__ == '__main__': sys.exit(main())
