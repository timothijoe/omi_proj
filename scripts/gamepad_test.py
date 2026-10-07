#!/usr/bin/env python3
"""Direct gamepad -> circle_test-compatible mm/degree increments.

Preview by default. --execute publishes after Enter. Hold RB to move.
A/B controls the project gripper by default; --no-gripper disables it.
"""
import argparse
import math
from pathlib import Path
import sys
import time

# Allow `python scripts/gamepad_test.py` without an editable package install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from omi_hil_rl.real.gamepad_control import Mapping, BTN_TR, wire_action
from omi_hil_rl.real.linux_gamepad import LinuxGamepad
from omi_hil_rl.real.gamepad_home import GamepadHome, add_home_arguments
from omi_hil_rl.real.gamepad_gripper import add_gripper_arguments, calibration_from_args, GamepadGripper
from omi_hil_rl.real.sdk_action import OUTPUT_CONVENTIONS, format_action_trace


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return value


def command_details(pad, mapping, convention='legacy'):
    """Read once: both the original and final command describe the same tick."""
    if not pad.poll():
        mode, action = 'disconnected', [0.]*6
    elif not pad.buttons.get(BTN_TR, False):
        mode, action = 'idle', [0.]*6
    else:
        mode, action = 'human', mapping.action(pad.axes)
    return mode, action, wire_action(action, convention)


def command(pad, mapping, convention='legacy'):
    mode, _, data = command_details(pad, mapping, convention)
    return mode, data


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--topic', default='auto',
                    help='Manual receiver input; auto reads the receiver configuration before publishing')
    ap.add_argument('--output-convention', choices=OUTPUT_CONVENTIONS, default='legacy',
                    help='Final wire frame/rotation format; SDK preset requires FRAME_BASE')
    ap.add_argument('--device', default='/dev/input/js0')
    ap.add_argument('--rate', type=positive, default=10., help='Commands per second')
    ap.add_argument('--scale', type=positive, default=1., help='Multiplier for both speeds')
    ap.add_argument('--speed-mm-s', type=positive, default=10.)
    ap.add_argument('--rotation-deg-s', type=positive, default=10.)
    ap.add_argument('--deadzone', type=float, default=.15)
    ap.add_argument('--signs', type=int, nargs=6, default=[1]*6, metavar='SIGN')
    add_gripper_arguments(ap)
    ap.set_defaults(
        gripper_server='192.168.14.11:55551',
        gripper_sdk_root=PROJECT_ROOT / 'local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py',
        gripper_calibration=PROJECT_ROOT / 'tutorials/gripper_limits.json')
    ap.add_argument('--no-gripper', action='store_true',
                    help='Disable A/B gripper control; otherwise use the project gripper defaults')
    add_home_arguments(ap)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    if args.no_gripper:
        args.gripper_server = None
    calibration = calibration_from_args(args, ap)
    if args.gripper_server:
        print(f'夹爪配置：{args.gripper_server}；A 闭合 / B 张开，无需 RB；'
              + ('SDK 控制将在开始后启用。' if args.execute else '仅预览，不连接夹爪。'), flush=True)
    else:
        print('夹爪已禁用（--no-gripper），A/B 不执行夹爪动作。', flush=True)
    try:
        mapping = Mapping(hz=args.rate, translation_m_s=args.speed_mm_s*args.scale/1000,
                          rotation_rad_s=math.radians(args.rotation_deg_s)*args.scale,
                          deadzone=args.deadzone, signs=tuple(args.signs))
    except ValueError as exc:
        ap.error(str(exc))
    print(f'平移最大 {mapping.translation_m_s*1000:g} mm/s，'
          f'旋转最大 {math.degrees(mapping.rotation_rad_s):g} degree/s，{args.rate:g} Hz。')
    home_hint = ('单按回位键返回初始末端位姿' if args.home_button_alone
                 else 'RB+回位键返回初始末端位姿，松开 RB 取消')
    print('按住 RB 移动；'+home_hint+'；右摇杆 XY，十字键上下 Z，左摇杆 Rx/Ry，十字键左右 Rz。')
    print('输出约定:', args.output_convention)
    if args.output_convention != 'legacy':
        print('SDK 输出为 [dx,dy,dz,dA,dB,dC]；接收端使用 FRAME_BASE=0 并核对 UserFrame。')
    else:
        print('每条命令：[dx,dy,dz,rx,ry,rz]，单位 mm/degree。')
    pad = LinuxGamepad(args.device)
    gripper = GamepadGripper(args, calibration, args.execute)
    node = pub = ros = None
    try:
        if args.execute:
            from omi_hil_rl.real.receiver_preflight import inspect_receiver
            try:
                route = inspect_receiver(args.topic, require_connected=True)
            except ValueError as exc:
                ap.error(f'接收端预检失败：{exc}')
            args.topic = route['manual_topic']
            import rclpy as ros
            from std_msgs.msg import Float64MultiArray
            from rclpy.signals import SignalHandlerOptions
            # Keep the ROS context alive until our Ctrl+C cleanup sends zero.
            ros.init(signal_handler_options=SignalHandlerOptions.NO)
            node = ros.create_node('eef_gamepad_test')
            pub = node.create_publisher(Float64MultiArray, args.topic, 1)
            print('接收端已发现，发送话题:', args.topic,
                  '；请确认接收端选择的机械臂，并停止其他动作发布程序。')
            input('按回车开始；随后按住 RB 才移动，Ctrl+C 退出：')
        else:
            print('仅手柄预览，无 ROS 发布；加 --execute 发送。Ctrl+C 退出。')
        gripper.start()
        home = GamepadHome(node, button_code=args.home_button_code,
                           require_rb=not args.home_button_alone)
        print(f'返回触发键码={args.home_button_code}；按 X 核对“按下按钮”，'
              '若键码不同，用 --home-button-code 指定。', flush=True)
        if args.execute and args.rate != 10.:
            print('回位要求 --rate 10；当前频率下禁用返回。')
        period = 1/args.rate
        previous, last_print = None, 0.
        previous_buttons, previous_status = None, None
        while ros is None or ros.ok():
            started = time.monotonic()
            mode, original, data = command_details(pad, mapping, args.output_convention)
            if node is not None:
                ros.spin_once(node, timeout_sec=0.)
            home_command = home.tick(mode != 'disconnected', pad.buttons) if args.rate == 10. else None
            convention = args.output_convention
            if home_command is not None:
                mode, original, data = home_command
                convention = 'sdk-base-aligned'
            if pub is not None:
                if node.count_publishers(args.topic) > 1:
                    raise RuntimeError('发现其他动作发布者，请先停止其他控制程序')
                pub.publish(Float64MultiArray(data=data))
            gripper.tick(mode != 'disconnected', pad.buttons)
            pressed_buttons = sorted(k for k, v in pad.buttons.items() if v)
            if (mode != previous or started-last_print >= .5 or
                    pressed_buttons != previous_buttons or home.status != previous_status):
                print(format_action_trace(mode, original, convention, data, pub is not None)+
                      f' | 返回={home.status}'+
                      f' | RB={bool(pad.buttons.get(BTN_TR, False))}'+
                      f' | X={bool(pad.buttons.get(args.home_button_code, False))}'+
                      f' | 按下按钮={pressed_buttons}'+
                      (f' | 错误={pad.error}' if mode == 'disconnected' else ''), flush=True)
                previous, last_print = mode, started
                previous_buttons, previous_status = pressed_buttons, home.status
            # No catch-up bursts and no enlarged delta after a scheduling delay.
            time.sleep(max(0., period-(time.monotonic()-started)))
    except KeyboardInterrupt:
        pass
    finally:
        pad.close()
        if node is not None:
            if ros.ok() and node.count_publishers(args.topic) == 1:
                pub.publish(Float64MultiArray(data=[0.]*6))
            node.destroy_node()
        if ros is not None and ros.ok():
            ros.shutdown()
        gripper.close()


if __name__ == '__main__':
    main()
