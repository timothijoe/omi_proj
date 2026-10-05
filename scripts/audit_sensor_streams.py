#!/usr/bin/env python3
"""Read-only ROS sensor rates, header ages, and producer counters. No SDK/control."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=10.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.duration <= 3600:
        parser.error('duration must be in (0, 3600] seconds')
    # Reserve output before subscribing so no existing report is overwritten.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as destination:
        import numpy as np
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        from geometry_msgs.msg import WrenchStamped
        from std_msgs.msg import String
        rclpy.init(args=[])
        node = rclpy.create_node('omi_readonly_sensor_audit', start_parameter_services=False)
        rows, statuses, subscriptions = {}, {}, []
        start = time.monotonic()+2
        def receive(msg, topic):
            now = time.monotonic()
            if now < start:
                return
            if isinstance(msg, String):
                try:
                    value = json.loads(msg.data)
                    state = statuses.setdefault(topic, dict(first=value, last=value, messages=0))
                    state['last'] = value
                    state['messages'] += 1
                except ValueError:
                    pass
            else:
                header = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
                rows.setdefault(topic, []).append((now, (time.time_ns()-header)/1e6, header))
        topics = {'/omi/wrist/color/image_roi': Image, '/omi/wrist/color/image_roi/record': Image,
                  '/omi/wrist/status': String}
        for side in 'ab':
            for field in ('deformation', 'shear', 'depth', 'wrench', 'status'):
                topics[f'/omi/tactile_grid24x16/{side}/{field}'] = (
                    String if field == 'status' else WrenchStamped if field == 'wrench' else Image)
        for topic, cls in topics.items():
            subscriptions.append(node.create_subscription(cls, topic, lambda m,t=topic: receive(m,t),
                QoSProfile(depth=128, reliability=ReliabilityPolicy.BEST_EFFORT)))
        try:
            while time.monotonic() < start+args.duration:
                rclpy.spin_once(node, timeout_sec=.05)
        finally:
            node.destroy_node()
            rclpy.shutdown()
        def summary(values):
            return dict(zip(('min','p50','p95','max'), map(float, np.percentile(values,[0,50,95,100])))) if len(values) else None
        report = dict(duration_s=args.duration, domain=os.environ.get('ROS_DOMAIN_ID'),
            timestamp_note='host header ages; SDK/device latency unknown',
            probe_qos='BEST_EFFORT depth 128; probe loss not proof of producer loss',
            topics={t: dict(count=len(v), average_hz=len(v)/args.duration,
                receive_gap_ms=summary(np.diff([r[0] for r in v])*1000),
                header_age_ms=summary([r[1] for r in v]),
                repeated_headers=sum(a[2]==b[2] for a,b in zip(v,v[1:]))) for t,v in rows.items()},
            status=statuses, missing_topics=sorted(set(topics)-set(rows)-set(statuses)))
        json.dump(report,destination,indent=2)
    print(args.output)


if __name__ == '__main__':
    main()
