#!/usr/bin/env python3
"""SpacePilot -> receiver manual mm/SDK-ABC increments; preview by default."""
import argparse
from pathlib import Path
import signal
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from omi_hil_rl.hardware.spacepilot_pose import SpaceNav
from omi_hil_rl.real.spacepilot_control import (
    DEFAULT_ENABLE_BUTTON, EnableGate, SpacePilotMapping, selected_action, MotionSchedule,
)
from omi_hil_rl.real.sdk_action import OUTPUT_CONVENTIONS, output_action, format_action_trace


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true', help='Preflight receiver, then publish after Enter')
    ap.add_argument('--topic', default='auto', help='Receiver manual topic; auto discovers it')
    ap.add_argument('--rate', type=float, default=10.)
    ap.add_argument('--scale', type=float, default=1., help='Common speed multiplier')
    ap.add_argument('--translation-scale', type=float, default=1., help='Independent translation multiplier; 0 disables')
    ap.add_argument('--rotation-scale', type=float, default=1., help='Independent rotation multiplier; 0 disables')
    ap.add_argument('--speed-mm-s', type=float, default=10.)
    ap.add_argument('--rotation-deg-s', type=float, default=10.)
    ap.add_argument('--deadzone', type=float, default=18., help='Raw input deadzone [0,350)')
    ap.add_argument('--mode', choices=('translation', 'rotation', 'all'), default='all')
    ap.add_argument('--dominant-axis', action='store_true')
    ap.add_argument('--debug-input', action='store_true',
                    help='Show device raw axes and mapped axes before enable/mode/scale')
    ap.add_argument('--signs', type=int, nargs=6, default=[1]*6)
    ap.add_argument('--enable-button', type=int, default=DEFAULT_ENABLE_BUTTON,
                    help='libspnav ID; default 19 per current physical key 3 report')
    ap.add_argument('--enable-mode', choices=('hold', 'toggle'), default='hold')
    ap.add_argument('--output-convention', choices=OUTPUT_CONVENTIONS, default='sdk-x-forward-z-left')
    return ap


def run(args, mapping, gate):
    ros = node = pub = None
    driver = SpaceNav(on_button=gate.on_button, on_reset=gate.reset)
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        if args.execute:
            from omi_hil_rl.real.receiver_preflight import inspect_receiver, discovery_environment
            print('ROS 发现环境：' + discovery_environment(), flush=True)
            route = inspect_receiver(args.topic, require_connected=True,
                                     expected_manual_rate=args.rate,
                                     allow_anonymous_subscriptions=True)
            args.topic = route['manual_topic']
            if route.get('anonymous_subscription_topics'):
                print('接收端订阅者节点名不可见；参数服务校验通过，按唯一订阅及消息类型匹配：'
                      + ', '.join(route['anonymous_subscription_topics']), flush=True)
            import rclpy as ros
            from rclpy.signals import SignalHandlerOptions
            from std_msgs.msg import Float64MultiArray
            ros.init(signal_handler_options=SignalHandlerOptions.NO)
            node = ros.create_node('eef_spacepilot_test')
            pub = node.create_publisher(Float64MultiArray, args.topic, 1)
            print(f'接收端已发现，手动话题：{args.topic}；请先停止其他手柄/策略动作发送程序。', flush=True)
            input('按回车开始读取设备；之后用指定设备按钮启用运动，Ctrl+C 退出：')
        else:
            print('仅预览，无 ROS 发布。Ctrl+C 退出。', flush=True)
        gate.reset()
        period = 1. / args.rate
        last_poll = time.monotonic()
        schedule = MotionSchedule(args.rate)
        last_print = 0.
        last_state = None
        while ros is None or ros.ok():
            now = time.monotonic()
            # Discard queued input after a process stall; require a fresh enable press.
            if now - last_poll > .25:
                driver.close()
                mapping.reset()
                driver.next_retry = now + .1
            last_poll = now
            driver.poll(now)
            mode, original = selected_action(driver, gate, mapping, time.monotonic())
            data = output_action(original, args.output_convention)
            if node is not None:
                ros.spin_once(node, timeout_sec=0.)
                if node.count_publishers(args.topic) > 1:
                    raise RuntimeError('发现其他手动动作发布者，请先停止其他控制程序')
                if node.count_publishers(route['policy_topic']) > 0:
                    raise RuntimeError('发现策略动作发布者，请先停止策略控制程序')
            # Start and stop edges bypass the deadline. While motion continues,
            # keep --rate even when its magnitude/direction changes; never catch up.
            send = schedule.due(now, data)
            if send:
                if pub is not None:
                    pub.publish(Float64MultiArray(data=data))
                schedule.sent(time.monotonic(), data)
            state = (mode, gate.enabled, driver.last_button, driver.name)
            if state != last_state or now - last_print >= .5:
                debug = (f' | 设备原始[x,y,z,rx,ry,rz]={driver.device_raw}'
                         f' | 映射后[X,Y,Z,Rx,Ry,Rz]={driver.raw}') if args.debug_input else ''
                print(format_action_trace(mode, original, args.output_convention, data,
                                          pub is not None and send) +
                      f' | 启用={gate.enabled} | 按钮={driver.last_button}' +
                      f' | 设备={driver.message}' + debug, flush=True)
                last_state, last_print = state, now
            time.sleep(min(.01, period))
    finally:
        # Try to stop before resource cleanup, including EOF, errors and signals.
        try:
            if pub is not None and ros.ok():
                pub.publish(Float64MultiArray(data=[0.] * 6))
        finally:
            driver.close()
            if node is not None:
                node.destroy_node()
            if ros is not None and ros.ok():
                ros.shutdown()
            signal.signal(signal.SIGTERM, previous_handler)


def main():
    ap = build_parser()
    args = ap.parse_args()
    try:
        mapping = SpacePilotMapping(
            rate=args.rate, speed_mm_s=args.speed_mm_s, rotation_deg_s=args.rotation_deg_s,
            scale=args.scale, translation_scale=args.translation_scale,
            rotation_scale=args.rotation_scale, deadzone=args.deadzone, mode=args.mode,
            dominant=args.dominant_axis, signs=tuple(args.signs))
        gate = EnableGate(args.enable_button, args.enable_mode)
        if args.execute and args.output_convention == 'legacy':
            raise ValueError('Receiver uses SDK ABC; choose an sdk output convention')
    except ValueError as exc:
        ap.error(str(exc))
    print(f'平移合速度上限 {mapping.linear_speed*1000:g} mm/s；'
          f'旋转角速度上限 {mapping.angular_speed*180/3.141592653589793:g} degree/s；{args.rate:g} Hz。')
    print(f'模式={args.mode}，输出={args.output_convention}，启用按钮 ID={args.enable_button} '
          f'({"按住运动，松开停止" if args.enable_mode == "hold" else "按下切换启停"})。')
    print('默认实体 3 是运动启用键；模式用 --mode 选择。本入口无夹爪和回位绑定。', flush=True)
    try:
        run(args, mapping, gate)
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError, OSError, EOFError) as exc:
        ap.exit(1, f'错误：{exc}\n')


if __name__ == '__main__':
    main()
