#!/usr/bin/env python3
"""circle_test.py — 仿照 axis_test.py，通过六维增量画半径3cm的圆。

默认在基座XY平面画一整圈，姿态不变，40秒、10Hz。
当前位置是圆周起点，圆心位于起点-X方向30mm；
相对起点范围：X [-60,0]mm、Y [-30,30]mm、Z不变。

用法：
    source /opt/ros/humble/setup.bash
    /usr/bin/python3.10 circle_test.py
    /usr/bin/python3.10 circle_test.py --radius-mm 30 --duration 40
    /usr/bin/python3.10 circle_test.py --plane xz
"""

import argparse
import math
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

PLANES = {'xy': (0, 1), 'xz': (0, 2), 'yz': (1, 2)}


def circle(radius_mm=30.0, duration=40.0, rate=10.0, plane='xy', clockwise=False):
    n_steps = max(1, round(duration * rate))
    axis_a, axis_b = PLANES[plane]
    points = []
    for i in range(n_steps + 1):
        u = i / n_steps
        # 首尾逐渐加减速，完整走过一圈。
        phase = 10 * u**3 - 15 * u**4 + 6 * u**5
        theta = (-1 if clockwise else 1) * 2 * math.pi * phase
        point = [0.0, 0.0, 0.0]
        point[axis_a] = radius_mm * (math.cos(theta) - 1)
        point[axis_b] = radius_mm * math.sin(theta)
        points.append(point)
    points[0] = [0.0, 0.0, 0.0]
    points[-1] = [0.0, 0.0, 0.0]
    actions = [
        [after[k] - before[k] for k in range(3)] + [0.0, 0.0, 0.0]
        for before, after in zip(points[:-1], points[1:])
    ]
    return points, actions


class CircleTest(Node):
    def __init__(self):
        super().__init__('circle_test')
        self.pub = self.create_publisher(Float64MultiArray, '/omi/action_test/decision', 10)

    def send_delta(self, t, r):
        msg = Float64MultiArray()
        msg.data = [float(v) for v in (t + r)]
        self.pub.publish(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--radius-mm', type=float, default=30.0, help='圆半径 mm (默认30)')
    ap.add_argument('--duration', type=float, default=40.0, help='画一圈的时间 秒 (默认40)')
    ap.add_argument('--rate', type=float, default=10.0, help='发布频率 Hz (默认10)')
    ap.add_argument('--plane', choices=PLANES, default='xy', help='基座坐标系内的画圆平面')
    ap.add_argument('--clockwise', action='store_true', help='反向画圆')
    ap.add_argument('--wait', type=float, default=2.0, help='画完后的停顿秒数')
    args = ap.parse_args()

    _, actions = circle(args.radius_mm, args.duration, args.rate, args.plane, args.clockwise)
    rclpy.init()
    node = CircleTest()
    period = 1.0 / args.rate

    input(f'\n在基座{args.plane.upper()}平面画半径{args.radius_mm}mm的一整圈，'
          f'姿态不变，共{len(actions)}步，{args.rate}Hz，约{len(actions)/args.rate:g}秒。\n'
          f'当前位置在圆周上，圆心在起点沿{args.plane[0].upper()}负方向{args.radius_mm}mm。\n'
          '确认机械臂周围安全、急停在手边后，按回车开始……')

    print(f'[{time.strftime("%H:%M:%S")}] 开始画圆')
    for action in actions:
        node.send_delta(action[:3], action[3:])
        time.sleep(period)

    time.sleep(args.wait)
    print('\n整圈动作发送完成。')
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
