#!/usr/bin/env python3
"""实时绘制最近 10 秒的 ROS 机器人动作指令。

运行：python3 tests/plot_action_decision.py
指定其他话题：python3 tests/plot_action_decision.py --topic /实际/动作话题
默认使用 run_async_rl.sh 的 ROS domain 13；可用 --domain 覆盖。
需要已加载 ROS 2 环境，并安装 matplotlib。
"""

import argparse
from collections import deque
import math
import os
import time

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray


DEFAULT_TOPICS = (
    "/omi/action/decision",           # 策略输出
    "/omi/action/manual_decision",    # 默认人工输出
    "/omi/controller_test/decision",  # 当前现场配置的人工输出
)
WINDOW_SECONDS = 10.0
LABELS = ("dx", "dy", "dz", "rx", "ry", "rz")


class ActionDecisionViewer(Node):
    def __init__(self, topics):
        super().__init__("action_decision_viewer")
        self.samples = {topic: deque() for topic in topics}
        self._action_subscriptions = [
            self.create_subscription(
                Float64MultiArray, topic,
                lambda msg, topic=topic: self.on_action(topic, msg), 10
            )
            for topic in topics
        ]

    def on_action(self, topic, msg):
        if len(msg.data) != 6 or not all(math.isfinite(value) for value in msg.data):
            self.get_logger().warning(f"忽略 {topic} 的非六维或含非有限值的动作消息")
            return
        self.samples[topic].append((time.monotonic(), tuple(msg.data)))

    def recent_samples(self, topic, now):
        samples = self.samples[topic]
        cutoff = now - WINDOW_SECONDS
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        return list(samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", dest="topics", metavar="TOPIC",
                        help="只显示指定话题；可重复指定多个")
    parser.add_argument("--domain", type=int,
                        default=int(os.environ.get("ROS_DOMAIN_ID", "13")),
                        help="ROS domain ID，默认使用环境变量 ROS_DOMAIN_ID，未设置时为 13")
    args = parser.parse_args()
    topics = tuple(dict.fromkeys(args.topics or DEFAULT_TOPICS))
    if any(not topic.startswith("/") for topic in topics):
        parser.error("话题名必须以 / 开头")
    if not 0 <= args.domain <= 232:
        parser.error("--domain 必须在 0 到 232 之间")
    if plt.get_backend().lower() == "agg":
        raise SystemExit("需要图形界面显示曲线；当前 Matplotlib 使用 Agg 后端。")

    rclpy.init(domain_id=args.domain)
    node = ActionDecisionViewer(topics)
    figure, axes = plt.subplots(len(topics), 2, squeeze=False, sharex=True,
                                figsize=(13, 3.3 * len(topics)))
    figure.suptitle(f"动作指令：最近 10 秒 | ROS_DOMAIN_ID={args.domain}")
    rows = []
    for topic, (translation_axis, rotation_axis) in zip(topics, axes):
        groups = []
        for axis, labels, unit in (
            (translation_axis, LABELS[:3], "mm"),
            (rotation_axis, LABELS[3:], "degree"),
        ):
            lines = [axis.plot([], [], label=label)[0] for label in labels]
            axis.axhline(0, color="gray", linewidth=0.8)
            axis.set_ylabel(unit)
            axis.legend(loc="upper left", ncol=3)
            axis.grid(True, alpha=0.3)
            axis.set_xlim(-WINDOW_SECONDS, 0)
            groups.append(lines)
        rows.append(groups)
    for axis in axes[-1]:
        axis.set_xlabel("相对当前时间 (s)")
    figure.tight_layout(rect=(0, 0, 1, 0.97))

    def update(_frame):
        # ROS 回调和 Matplotlib 都在主线程执行，无需跨线程共享数据。
        for _ in range(100):
            rclpy.spin_once(node, timeout_sec=0.0)
        now = time.monotonic()
        artists = []
        for row_index, (topic, (translation_lines, rotation_lines)) in enumerate(zip(topics, rows)):
            samples = node.recent_samples(topic, now)
            axes[row_index, 0].set_title(
                f"{topic} | 发布者 {node.count_publishers(topic)} | 10秒内 {len(samples)} 条"
            )
            times = [stamp - now for stamp, _values in samples]
            for axis, lines, offset in (
                (axes[row_index, 0], translation_lines, 0),
                (axes[row_index, 1], rotation_lines, 3),
            ):
                values = [value for _stamp, sample in samples
                          for value in sample[offset:offset + 3]]
                for index, line in enumerate(lines):
                    line.set_data(times, [sample[offset + index]
                                          for _stamp, sample in samples])
                low, high = (min(values + [0]), max(values + [0])) if values else (-1, 1)
                padding = max((high - low) * 0.1, 0.01)
                axis.set_ylim(low - padding, high + padding)
                artists.extend(lines)
        return artists

    animation = FuncAnimation(figure, update, interval=50, cache_frame_data=False)
    try:
        plt.show()
    finally:
        animation.event_source.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
