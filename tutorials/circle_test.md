# 右臂六维增量画圆

当前脚本已按用户要求简化为原axis_test.py的运行方式：创建publisher，回车后循环发布，
每次time.sleep(1/rate)，结束后等待并退出。没有--execute、反馈订阅、日志记录或额外门控。
工作区脚本`scripts/circle_test.py`与交付副本`/home/zhoutong/Downloads/oct04/robot_pose/circle_test.py`一致。

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3.10 circle_test.py
```

话题`/omi/action_test/decision`，Float64MultiArray，空layout，队列深度10。
每条`[dx,dy,dz,0,0,0]`，平移mm、旋转度，保持原axis_test发送格式。
默认基座XY平面，半径30mm，40秒一圈、10Hz、400条，结束等待2秒。
当前位置在圆周上，圆心-X30mm，相对起点X范围[-60,0]mm、Y[-30,30]mm、Z不变。
可用--radius-mm、--duration、--rate、--plane xy/xz/yz、--clockwise、--wait调整。
与原脚本一样sleep在每次发布后执行，40秒是名义时间，实际包含调度开销。

圆周轨迹`x=r(cosθ-1), y=r sinθ`，θ=2π(10u³−15u⁴+6u⁵)，u=t/T。
动作是相邻点的位置差，首尾渐变速度，默认最大单步0.88353mm。
不裁剪动作、不调整真实反馈，也不自动判断机械臂是否画成圆。

简化版三个平面/两种方向共6项几何测试通过，交付文件语法检查通过，未向真机发送。
`local/eef_replay/circle_r30_xy/preview.png`与CSV仍适用；该目录mock日志属于简化前版本的历史测试。
