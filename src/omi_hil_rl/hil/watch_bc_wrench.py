"""Read-only Start-to-baseline wrench monitor; never publishes robot commands."""
import argparse
import json
import math
import time
import uuid

from .bc_wrench_monitor import BCWrenchMonitor
from .periodic_control import _banner
from omi_hil_rl.real.linux_gamepad import LinuxGamepad


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return number


def live_status(monitor, now):
    result = {}
    for side in ('a', 'b'):
        recent = monitor.recent[side]
        if not recent or now - recent[-1][0] > .2:
            result[side] = dict(state='MISSING_OR_STALE', samples=len(recent))
            continue
        values = recent[-1][1]
        if not any(values):
            result[side] = dict(state='ALL_ZERO', samples=len(recent))
            continue
        entry = dict(state='LIVE', samples=len(recent), values=values)
        if monitor.active is not None:
            base = monitor.active['baseline'][side]
            entry['delta_force_xy'] = math.hypot(values[0] - base[0], values[1] - base[1])
            entry['delta_torque'] = math.dist(values[3:], base[3:])
        result[side] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gamepad', default='/dev/input/js0')
    parser.add_argument('--wrench-force-xy-warning', type=positive, default=1.5)
    parser.add_argument('--wrench-torque-warning', type=positive, default=.4)
    parser.add_argument('--duration', type=positive, help='optional monitor duration in seconds')
    args = parser.parse_args()

    import rclpy
    from geometry_msgs.msg import WrenchStamped
    from rclpy.qos import qos_profile_sensor_data
    rclpy.init()
    node = rclpy.create_node('omi_bc_wrench_watch', enable_rosout=False,
                             start_parameter_services=False)
    pad = LinuxGamepad(args.gamepad)
    def warning(event):
        print('BC_WRENCH_WARNING: ' + json.dumps(event, ensure_ascii=False), flush=True)
        _banner(f"触觉差值预警：{event['side'].upper()} 指 Fx/Fy 差模 "
                f"{event['force_xy']:.3f}，力矩差模 {event['torque']:.3f}", '33')
    monitor = BCWrenchMonitor(force_xy_limit=args.wrench_force_xy_warning,
                              torque_limit=args.wrench_torque_warning, emit=warning)
    for side in ('a', 'b'):
        def receive(message, side=side):
            wrench = message.wrench
            monitor.ingest(side, (wrench.force.x, wrench.force.y, wrench.force.z,
                                  wrench.torque.x, wrench.torque.y, wrench.torque.z), time.monotonic())
        node.create_subscription(WrenchStamped,
            f'/omi/tactile_grid24x16/{side}/wrench', receive, qos_profile_sensor_data)
    print('BC_WRENCH_WATCH: read-only; no action publishers; Start(315)=capture baseline; '
          'Ctrl+C=exit; baseline-relative warnings only', flush=True)
    _banner('离开接口、夹持稳定后按手柄 Start(315) 记录双指基线', '36')
    started = time.monotonic()
    next_status = 0.
    next_pad_error = 0.
    try:
        while args.duration is None or time.monotonic() - started < args.duration:
            rclpy.spin_once(node, timeout_sec=.01)
            now = time.monotonic()
            connected = pad.poll()
            if not connected and now >= next_pad_error:
                print('BC_WRENCH_GAMEPAD: ' + pad.error, flush=True)
                next_pad_error = now + 5.
            for code, pressed, initial in pad.button_events:
                if code == 315 and pressed and not initial:
                    if monitor.active is not None:
                        print('BC_WRENCH_SUMMARY: ' + json.dumps(
                            monitor.finish(monitor.active['episode']), ensure_ascii=False), flush=True)
                    result = monitor.begin(uuid.uuid4().hex, now)
                    print('BC_WRENCH_BASELINE: ' + json.dumps(result, ensure_ascii=False), flush=True)
                    _banner('双指基线已记录；仅预警，不控制机械臂' if result['status'] == 'monitoring'
                            else '双指基线不可用：请检查消息、全零和夹持稳定性',
                            '36' if result['status'] == 'monitoring' else '33')
            if now >= next_status:
                print('BC_WRENCH_LIVE: ' + json.dumps(live_status(monitor, now), ensure_ascii=False),
                      flush=True)
                next_status = now + 1.
    except KeyboardInterrupt:
        pass
    finally:
        if monitor.active is not None:
            print('BC_WRENCH_SUMMARY: ' + json.dumps(
                monitor.finish(monitor.active['episode']), ensure_ascii=False), flush=True)
        pad.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
