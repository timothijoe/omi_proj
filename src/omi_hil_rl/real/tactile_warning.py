"""Subscribe to raw wrench values and log threshold warnings; no control output."""
import argparse
import logging
import math
from pathlib import Path
import time


class WarningMonitor:
    """Per-finger raw vector norms, force OR torque, with rate-limited logs."""
    def __init__(self, emit, *, force_limit=None, torque_limit=None, log_interval=1.):
        if force_limit is None and torque_limit is None:
            raise ValueError('provide at least one force/torque limit')
        for value in (force_limit, torque_limit, log_interval):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError('limits/log interval must be finite and positive')
        self.emit = emit
        self.force_limit, self.torque_limit = force_limit, torque_limit
        self.log_interval = log_interval
        self.last_log = {}

    def receive(self, side, values, now):
        values = tuple(float(v) for v in values)
        if len(values) != 6 or not all(math.isfinite(v) for v in values):
            self._warn((side, 'invalid'), now, '%s: invalid wrench values: %s' % (side, values))
            return
        force, torque = math.hypot(*values[:3]), math.hypot(*values[3:])
        exceeded = []
        if self.force_limit is not None and force >= self.force_limit:
            exceeded.append('|F|=%.5f >= %.5f' % (force, self.force_limit))
        if self.torque_limit is not None and torque >= self.torque_limit:
            exceeded.append('|T|=%.5f >= %.5f' % (torque, self.torque_limit))
        if exceeded:
            self._warn((side, 'overload'), now,
                       '%s: %s; Fx/Fy/Fz=%s; Tx/Ty/Tz=%s (raw SDK units)' % (
                           side, ' OR '.join(exceeded), values[:3], values[3:]))

    def _warn(self, key, now, message):
        previous = self.last_log.get(key)
        if previous is None or now - previous >= self.log_interval:
            self.last_log[key] = now
            self.emit(message)


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force-limit', type=positive, help='raw sqrt(Fx^2+Fy^2+Fz^2) threshold')
    parser.add_argument('--torque-limit', type=positive, help='raw sqrt(Tx^2+Ty^2+Tz^2) threshold')
    parser.add_argument('--log-interval', type=positive, default=1., help='seconds between warnings per finger')
    parser.add_argument('--log-file', type=Path, help='optional NEW log file; refuses to overwrite')
    parser.add_argument('--topic-a', default='/omi/tactile_grid24x16/a/wrench')
    parser.add_argument('--topic-b', default='/omi/tactile_grid24x16/b/wrench')
    args = parser.parse_args()
    if args.force_limit is None and args.torque_limit is None:
        parser.error('provide --force-limit and/or --torque-limit')
    handlers = [logging.StreamHandler()]
    if args.log_file:
        try:
            handlers.append(logging.FileHandler(args.log_file, mode='x', encoding='utf-8'))
        except OSError as exc:
            parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=handlers)
    logger = logging.getLogger('tactile_warning')
    monitor = WarningMonitor(logger.warning, force_limit=args.force_limit,
                             torque_limit=args.torque_limit, log_interval=args.log_interval)
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from geometry_msgs.msg import WrenchStamped
    rclpy.init()
    node = rclpy.create_node('omi_tactile_warning')
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    def receive(side, msg):
        w = msg.wrench
        monitor.receive(side, [w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z],
                        time.monotonic())
    subscriptions = [node.create_subscription(WrenchStamped, topic,
                     lambda msg, side=side: receive(side, msg), qos)
                     for side, topic in (('A', args.topic_a), ('B', args.topic_b))]
    logger.info('WARNING ONLY; force_limit=%s torque_limit=%s interval=%ss; raw SDK units, NO baseline subtraction',
                args.force_limit, args.torque_limit, args.log_interval)
    logger.info('Listening: A=%s B=%s; no robot SDK, no action publishers. Ctrl+C to exit.', args.topic_a, args.topic_b)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        logging.shutdown()


if __name__ == '__main__':
    main()
