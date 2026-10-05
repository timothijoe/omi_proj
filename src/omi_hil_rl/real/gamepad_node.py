"""10 Hz gamepad/policy arbiter. Preview by default; --publish sends robot deltas."""
import argparse
import json
import math
import time
from pathlib import Path

from .gamepad_control import Mapping, Arbiter, BTN_TR, wire_action
from .linux_gamepad import LinuxGamepad
from .gamepad_home import GamepadHome, add_home_arguments
from .gamepad_gripper import add_gripper_arguments, calibration_from_args, GamepadGripper
from .sdk_action import OUTPUT_CONVENTIONS, format_action_trace


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', default='/dev/input/js0')
    p.add_argument('--publish', action='store_true')
    p.add_argument('--topic', default='/omi/action/decision')
    p.add_argument('--manual-topic', default='/omi/action/manual_decision')
    p.add_argument('--policy-topic', default='/omi/policy/candidate')
    p.add_argument('--output-convention', choices=OUTPUT_CONVENTIONS, default='legacy')
    p.add_argument('--frame', default='base', help='Required policy header frame_id')
    p.add_argument('--speed-mm-s', type=float, default=10.)
    p.add_argument('--rotation-deg-s', type=float, default=10.)
    p.add_argument('--policy-timeout', type=float, default=.2)
    p.add_argument('--candidate-expiry', choices=('on','off'), default='on')
    p.add_argument('--duration',type=float,help='Optional bounded preview/run duration in seconds')
    p.add_argument('--deadzone', type=float, default=.15)
    p.add_argument('--signs', type=int, nargs=6, default=[1]*6, metavar='SIGN')
    p.add_argument('--log', type=Path, help='Optional JSONL of selected/sent commands, not measured motion')
    add_gripper_arguments(p)
    add_home_arguments(p)
    args = p.parse_args()
    calibration = calibration_from_args(args, p)
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration<=0):p.error('duration must be positive and finite')
    if not math.isfinite(args.policy_timeout) or args.policy_timeout<=0:p.error('policy timeout must be positive and finite')
    if len({args.topic, args.manual_topic, args.policy_topic}) != 3:
        p.error('Policy input, policy output and manual output must be different topics')
    try:
        mapping = Mapping(translation_m_s=args.speed_mm_s/1000,
                          rotation_rad_s=math.radians(args.rotation_deg_s),
                          deadzone=args.deadzone, signs=tuple(args.signs))
    except ValueError as exc:
        p.error(str(exc))
    import rclpy
    from geometry_msgs.msg import TwistStamped
    from std_msgs.msg import Float64MultiArray
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node('omi_gamepad_control')
    qos = QoSProfile(depth=1, durability=DurabilityPolicy.VOLATILE)
    publisher = node.create_publisher(Float64MultiArray, args.topic, qos) if args.publish else None
    manual_publisher = node.create_publisher(Float64MultiArray, args.manual_topic, qos) if args.publish else None
    from .gamepad_control import command_routes
    publishers = {'policy': publisher, 'manual': manual_publisher}
    topics = {'policy': args.topic, 'manual': args.manual_topic}
    previous_route = None
    arbiter, pad = Arbiter(mapping,args.policy_timeout,candidate_expiry=args.candidate_expiry=='on'), LinuxGamepad(args.device)
    log = args.log.open('x') if args.log else None
    def now():
        return node.get_clock().now().nanoseconds/1e9
    offered=accepted=0
    def receive(msg):
        nonlocal offered,accepted
        offered+=1
        if msg.header.frame_id != args.frame:
            arbiter.policy = None
            return
        t = msg.twist
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec/1e9
        accepted+=int(arbiter.offer([t.linear.x, t.linear.y, t.linear.z,
                       t.angular.x, t.angular.y, t.angular.z], stamp, now()))
    node.create_subscription(TwistStamped, args.policy_topic, receive, qos)
    gripper = GamepadGripper(args, calibration, args.publish)
    home = GamepadHome(node, button_code=args.home_button_code)
    previous, last_print, last_clock = None, 0., None
    previous_buttons, previous_status = None, None
    def tick():
        nonlocal previous, last_print, last_clock, previous_buttons, previous_status, previous_route
        clock = now()
        if last_clock is not None and clock < last_clock:
            arbiter.policy = None
            arbiter.barrier = clock
            arbiter.last_stamp = float('-inf')
        last_clock = clock
        connected = pad.poll()
        mode, delta = arbiter.select(connected, pad.buttons.get(BTN_TR, False), pad.axes, clock)
        data = wire_action(delta, args.output_convention)
        home_command = home.tick(connected, pad.buttons)
        convention = args.output_convention
        if home_command is not None:
            mode, delta, data = home_command
            convention = 'sdk-base-aligned'
        # Only this node may publish the final command topic.
        conflict = bool(publisher and any(node.count_publishers(t) > 1 for t in topics.values()))
        if conflict:
            raise RuntimeError('Another publisher owns '+args.topic+'; stop the other controller first')
        selected_route, routed = command_routes(mode, data, previous_route)
        if publisher:
            previous_route = selected_route
            for route, payload in routed:
                publishers[route].publish(Float64MultiArray(data=payload))
        row = dict(time=clock, source=mode, intervention=selected_route == 'manual',
                   action_m_rad=delta.tolist(), command_mm_deg=data, published=bool(publisher),
                   output_convention=convention, home_status=home.status,
                   conversion_enabled=convention != 'legacy',
                   original_mm_rotvec_deg=wire_action(delta))
        row['command_topic'] = topics[selected_route]
        row.update(policy_frame=args.frame,policy_topic=args.policy_topic,policy_offered=offered,
                   candidate_expiry=args.candidate_expiry,
                   selected_policy_age_ms=None if arbiter.selected_policy_stamp is None else (clock-arbiter.selected_policy_stamp)*1000,
                   policy_accepted=accepted,selected_policy_reference_ns=None if arbiter.selected_policy_stamp is None else round(arbiter.selected_policy_stamp*1e9),
                   gamepad_connected=connected,rb_held=bool(pad.buttons.get(BTN_TR,False)),
                   gamepad_axes=dict(pad.axes),gamepad_buttons=dict(pad.buttons),
                   axis_swap_enabled=convention=='sdk-x-forward-z-left',
                   rotation_abc_enabled=convention!='legacy')
        row["gripper_command"] = gripper.tick(connected, pad.buttons)
        if log:
            log.write(json.dumps(row)+'\n'); log.flush()
        pressed_buttons = sorted(k for k, v in pad.buttons.items() if v)
        if (mode != previous or time.monotonic()-last_print >= 1 or
                pressed_buttons != previous_buttons or home.status != previous_status):
            print(format_action_trace(mode, delta, convention, data, bool(publisher))+
                  f' | 返回={home.status}'+
                  f' | 手柄连接={connected} | RB={bool(pad.buttons.get(BTN_TR,False))}'+
                  f' | X={bool(pad.buttons.get(args.home_button_code,False))}'+
                  f' | 返回触发键码={args.home_button_code}'+
                  f' | 按下按钮={pressed_buttons}'+
                  (f' | 错误={pad.error}' if pad.error else ''), flush=True)
            previous, last_print = mode, time.monotonic()
            previous_buttons, previous_status = pressed_buttons, home.status
    # Wall/steady timer: use_sim_time or clock jumps must not stall input polling.
    from rclpy.clock import Clock, ClockType
    node.create_timer(1/mapping.hz, tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
    print(('PUBLISH policy='+args.topic+' manual='+args.manual_topic if publisher else 'PREVIEW: no robot publisher')+
          '; units mm/deg; hold RB to intervene; output='+args.output_convention, flush=True)
    try:
        gripper.start()
        started=time.monotonic()
        while rclpy.ok() and (args.duration is None or time.monotonic()-started<args.duration):
            rclpy.spin_once(node,timeout_sec=.05)
    except KeyboardInterrupt:
        pass
    finally:
        if publisher and rclpy.ok():
            for route, pub in publishers.items():
                if node.count_publishers(topics[route]) == 1:
                    pub.publish(Float64MultiArray(data=[0.]*6))
        pad.close()
        if log:
            log.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        gripper.close()


if __name__ == '__main__':
    main()
