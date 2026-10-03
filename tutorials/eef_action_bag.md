# 末端动作 rosbag 与模拟控制端联调

从 `omi_proj/` 执行。依赖本机 ROS Jazzy、rosbag2 MCAP 插件和项目 `.venv`。
入口仅启动本机 domain96 的测试节点，无 SDK 连接或真机运动。

## 生成并测试

```bash
bash scripts/eef_action_bag.sh generate --output local/action_test/my_trajectory
bash scripts/eef_action_bag.sh verify \
  --dataset local/action_test/my_trajectory \
  --output local/action_test/my_verification
```

输出目录必须不存在，避免覆盖实验。`verify` 自动启动真实 `ros2 bag play`，
经 DDS 向模拟控制端发送消息，约需 28 秒。
域按 `OMI_ACTION_TEST_DOMAIN_ID`、已有 `ROS_DOMAIN_ID`、默认96的优先级选择。
选未运行其他发布者的实验域。默认仅本机发现；需要跨电脑测试时显式设置
`OMI_ACTION_TEST_NETWORK=1`，启用子网发现。接收端需要相同domain、允许网络发现、
兼容QoS和可达网络；此开关本身不保证Jazzy与Humble兼容。
修改环境后要重新启动节点，已运行节点不会跟随终端环境变化。
`generate`仅写文件；`verify`仅在约24秒回放期间发布动作，结束后不会持续发布。

生成目录包含：

- `commands/`：可直接供 rosbag2 回放的 MCAP 包，240 条动作。
- `manifest.json`：动作契约、初始位姿、每帧动作、阶段、时间戳和预期目标。

验证目录包含：

- `received/`：接收端实际收到的动作，以及它生成并发布的模拟目标位姿。
- `report.json`：帧数、轨迹误差、返回误差、实际接收间隔、是否通过。
- `player.log`：ROS 回放日志。

## 每帧消息及动作顺序

话题 `/omi/action_test/decision`，类型 `std_msgs/msg/Float64MultiArray`。

```text
data = [dx, dy, dz, rx, ry, rz]
layout.dim[0].label = "left-eef-base-delta-v1:dx,dy,dz[m];rx,ry,rz[rad]"
layout.dim[0].size = 6
layout.dim[0].stride = 6
layout.data_offset = 0
```

平移单位米；旋转是基座系旋转向量，单位弧度，不是欧拉角目标或速度。
沿用策略动作的 `p_target = p_current + dp`、`R_target = Exp(dr) R_current`。
`base_link` 为约定坐标系，消息布局标签标识该版本；MultiArray 本身没有 Header。

默认方向是待现场确认的实验约定：前进 +X，右移 -Y，上移 +Z。

| 阶段 | 动作总量 | 时长 |
|---|---|---|
| 1–3 | +X 5 cm、-Y 5 cm、+Z 5 cm | 各 2 s |
| 4–6 | 绕基座 X、Y、Z 正向各 10°，原地改变姿态 | 各 2 s |
| 7–9 | 绕基座 Z、Y、X 反向各 10° | 各 2 s |
| 10–12 | -Z 5 cm、+Y 5 cm、-X 5 cm | 各 2 s |

10 Hz，每段20帧；五次多项式 `s(u)=10u³−15u⁴+6u⁵` 分配增量，
每帧只发送 `总量 × [s((k+1)/20)−s(k/20)]`。
末段由完整正向动作数组倒序取负得到；旋转不能保持原顺序直接取负。
每帧在名义 0.1 s 执行区间开始时发出，首末消息相隔23.9秒，
包含最后一帧的执行区间后名义轨迹时长24秒。

可选参数：`--hz 10 --seconds 2 --distance 0.05 --angle-deg 5 --right-sign -1`。
`--initial-pose X Y Z QX QY QZ QW` 指定模拟初始位姿，默认原点及单位四元数。
这些参数不代表实机允许的速度或工作空间。

## 验证范围与真机接入

本次已验证 `rosbag play → Float64MultiArray 订阅 → 增量转目标位姿 → 模拟目标发布/录制`。
目标话题 `/omi/action_test/mock_target` 使用 `geometry_msgs/msg/PoseStamped`。
模拟控制器假设上一目标立即成为当前反馈，没有动力学、IK、限位或伺服跟踪模拟。
记录中的目标来自模拟控制端，不是真机测量，也没有独立目标订阅者的交付确认。

接收端校验布局、长度、有限数值、实验增量上限及预期动作顺序，
错误后停止累加目标，报告失败；整段帧数及每帧位姿也必须匹配。
该顺序检查依赖已知测试轨迹，不能保证一般在线流的重复/陈旧帧识别。
MultiArray 没有采样时间、序号和有效期；录包时间与 manifest 索引仅供本次审计。

接真机前需要确认控制节点、话题、TCP/基座约定、右方向、转角及运动授权。
适配器应从新鲜实测位姿计算目标，接入现有控制器支持的笛卡尔接口或经校准的 IK，
并明确动作过期、断流停止、限位和跟踪误差处理。当前 Tianji SDK 适配器只有关节目标接口；
不能直接把这六个数转发成七关节目标。
实际位姿与目标应另外录制，才能检查真正的“两秒完成”和回到起点。

已有结果：[首次联调记录](../docs/agent/training/chronicles/2026-10-03-action-bag.md)。
