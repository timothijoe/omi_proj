"""10 Hz gamepad/policy arbiter. Preview by default; --publish sends robot deltas."""
import argparse
import json
import math
import time
from pathlib import Path

from .gamepad_control import Mapping, Arbiter, BTN_TR, wire_action
from .linux_gamepad import LinuxGamepad
from .sdk_action import OUTPUT_CONVENTIONS, format_action_trace


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', default='/dev/input/js0')
    p.add_argument('--publish', action='store_true')
    p.add_argument('--topic', default='/omi/action/decision')
    p.add_argument('--policy-topic', default='/omi/policy/candidate')
    p.add_argument('--output-convention', choices=OUTPUT_CONVENTIONS, default='legacy')
    p.add_argument('--frame', default='base', help='Required policy header frame_id')
    p.add_argument('--speed-mm-s', type=float, default=10.)
    p.add_argument('--rotation-deg-s', type=float, default=10.)
    p.add_argument('--deadzone', type=float, default=.15)
    p.add_argument('--signs', type=int, nargs=6, default=[1]*6, metavar='SIGN')
    p.add_argument('--log', type=Path, help='Optional JSONL of selected/sent commands, not measured motion')
    args = p.parse_args()
    if args.topic == args.policy_topic:
        p.error('Policy input and robot output must be different topics')
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
    rclpy.init()
    node = rclpy.create_node('omi_gamepad_control')
    qos = QoSProfile(depth=1, durability=DurabilityPolicy.VOLATILE)
    publisher = node.create_publisher(Float64MultiArray, args.topic, qos) if args.publish else None
    arbiter, pad = Arbiter(mapping), LinuxGamepad(args.device)
    log = args.log.open('x') if args.log else None
    def now():
        return node.get_clock().now().nanoseconds/1e9
    def receive(msg):
        if msg.header.frame_id != args.frame:
            arbiter.policy = None
            return
        t = msg.twist
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec/1e9
        arbiter.offer([t.linear.x, t.linear.y, t.linear.z,
                       t.angular.x, t.angular.y, t.angular.z], stamp, now())
    node.create_subscription(TwistStamped, args.policy_topic, receive, qos)
    previous, last_print, last_clock = None, 0., None
    def tick():
        nonlocal previous, last_print, last_clock
        clock = now()
        if last_clock is not None and clock < last_clock:
            arbiter.policy = None
            arbiter.barrier = clock
            arbiter.last_stamp = float('-inf')
        last_clock = clock
        connected = pad.poll()
        mode, delta = arbiter.select(connected, pad.buttons.get(BTN_TR, False), pad.axes, clock)
        data = wire_action(delta, args.output_convention)
        # Only this node may publish the final command topic.
        conflict = bool(publisher and node.count_publishers(args.topic) > 1)
        if conflict:
            raise RuntimeError('Another publisher owns '+args.topic+'; stop the other controller first')
        if publisher:
            publisher.publish(Float64MultiArray(data=data))
        row = dict(time=clock, source=mode, intervention=mode == 'human',
                   action_m_rad=delta.tolist(), command_mm_deg=data, published=bool(publisher),
                   output_convention=args.output_convention,
                   conversion_enabled=args.output_convention != 'legacy',
                   original_mm_rotvec_deg=wire_action(delta)))
        if log:
            log.write(json.dumps(row)+'\n'); log.flush()
        if mode != previous or time.monotonic()-last_print >= 1:
            print(format_action_trace(mode, delta, args.output_convention, data, bool(publisher))+
                  (f' | 错误={pad.error}' if pad.error else ''), flush=True)
            previous, last_print = mode, time.monotonic()
    # Wall/steady timer: use_sim_time or clock jumps must not stall input polling.
    from rclpy.clock import Clock, ClockType
    node.create_timer(1/mapping.hz, tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
    print(('PUBLISH '+args.topic if publisher else 'PREVIEW: no robot publisher')+
          '; units mm/deg; hold RB to intervene; output='+args.output_convention, flush=True)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if publisher and rclpy.ok() and node.count_publishers(args.topic) == 1:
            publisher.publish(Float64MultiArray(data=[0.]*6))
        pad.close()
        if log:
            log.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
