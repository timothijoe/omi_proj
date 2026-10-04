# 2026-10-04：实时 RViz 阶段总结与 EEF 对齐遗留

## 当前决定

按用户要求，暂时保留当前实时可视化版本。本次只整理记录，不继续修改关节映射、URDF、基座变换或 TCP 偏移。

**实时关节与末端消息已接通，双臂模型可以显示；end effector 与模型末端仍没有完全对应上，尚未完成几何对齐确认。**

这里的“保留版本”指保留当前工作区实现，并非新增 Git commit/tag。

## 启动与显示

在项目根目录运行：

```bash
bash scripts/view_grid_observation_live.sh --hz 10
```

默认 ROS domain 13；`--hz` 控制看板刷新，省略时为 2 Hz，不代表传感器发布频率。
关闭 RViz 或启动终端 Ctrl+C 结束该看板。该工具只订阅数据并发布可视化结果，不发送机器人运动命令。

使用原来的方向修正版模型：

```text
local/models/omi_marvin_stand_axis_corrected_v1/urdf/omi_marvin_stand_axis_corrected_v1.urdf
```

三维区展示完整双臂模型，并增加以下标记：

| 标记 | 含义 |
| --- | --- |
| 青色球、小 RGB 坐标轴 | 左臂 URDF L7 原点，不是已确认的 TCP |
| 品红色球、大 RGB 坐标轴 | `/tj/info/eef_left` 的位置与姿态 |
| 黄色连线 | L7 与 ROS EEF 的位置差 |
| 数字标签 | 距离、坐标轴相对转角、两个最新消息的时间差 |

模型使用 `/omi/live_grid/model/` 下独立的关节和 TF 话题；比较标记发布到 `/omi/live_grid/model_markers`。
保留原显示假设：消息 `base_link` 与模型根重合。不施加拟合的 TCP 偏移。
可视化取独立最新样本；消息过期或缺失时提示，关节 TF 可能保留最后姿态，不补零伪造实时状态。

## 已解决：现场 Jointfeedback 解码失败

此前能发现 `/tj/info/joint_feedback` 发布者，但看板收到 0 条。进一步检查发现：原始序列化字节可以约 50 Hz 接收，按本机旧类型反序列化却报 Fast CDR 异常。

用户提供的现场定义为：

```text
std_msgs/Header header
float64[14] positions
float64[14] velocities
float64[14] efforts
```

旧录包定义则使用 `arm_positions / arm_velocities / arm_efforts`，并包含躯干、头部数组。
两者类型名都为 `marvin_msgs/msg/Jointfeedback`，但字段布局不同：本次空 frame_id 样本现场为 356 字节，旧定义序列化为 572 字节。

修复采用独立消息包：

- 现场接口源码：`ros2/live_feedback_interfaces/marvin_msgs/`。
- 编译结果：`local/live_feedback_ws/`。
- 实时脚本加载现场接口的 `local_setup.bash`，可由 `OMI_LIVE_MARVIN_MSGS_SETUP` 指定。
- 实时订阅读取 `positions`；历史录包的 `arm_positions` 解码逻辑不改。

没有覆盖历史消息定义。新旧接口应在对应进程中分别加载，同一类型名称不能作为布局兼容的依据；其他旧脚本不会因此自动兼容现场新消息。

## 实测数据与左右臂检查

不同时间段的现场发布情况有变化，以下记录不是永久可用性保证：

- 双相机、双指 deformation/shear/depth 曾实测约 27–31 Hz。
- 新现场消息定义独立验证 5 秒收到 250 条关节反馈，约 50 Hz。
- 之后核对 6 秒收到 301 条关节反馈、300 条 `eef_left`，没有收到 `eef_right`。
- 最后核对时，positions 前 7 项有值、后 7 项全零，符合当前左臂反馈的顺序约定；之前曾是前 7 零、后 7 非零。
- 显示程序保留“前 7 左、后 7 右”和原弧度约定，没有人为交换左右或再次翻转修正版 URDF 的轴。
- 模型左右臂 14 个动态 TF 均已收到；关节、EEF 看板状态为 LIVE。

**50 Hz 是独立轻量订阅测得的源消息接收频率。** 带图像渲染的当前看板曾仅处理约 7 Hz 的关节/EEF 回调，不能将其标称 `--hz 10` 或源频率视为实时显示性能保证。

## 重点遗留：end effector 尚未与模型完全对应

在原基座重合假设下，按当前左臂关节角计算 L7，并与 ROS EEF 比较：

| 点位（米） | X | Y | Z |
| --- | ---: | ---: | ---: |
| 左臂模型 L7 原点 | 0.243646 | 0.152127 | 0.862724 |
| ROS EEF | 0.537701 | 0.312356 | 0.843290 |

本次差异：

- 空间距离约 **0.33544 m（33.5 cm）**。
- 坐标轴相对旋转角约 **120°**。
- 在 L7 局部坐标系下，EEF 平移约 **[0.174285, -0.286593, 0.002958] m**。
- 用最近时间戳配对的 300 个样本，最大配对时间差约 9.79 ms。
- 这 6 秒内机械臂基本静止，关节变化最大约 1.22×10⁻⁵ rad；差异稳定不能证明跨姿态的固定工具变换成立。

L7 原点不等于经过确认的法兰中心或 TCP，因此 **33.5 cm 不能直接解释为 TCP 定位误差**。但本次关系也不同于旧录包推断的约 23.3 cm、90°，不能直接沿用旧推断宣布对齐。

待后续核对：发布端 EEF 的实际参考基座、末端/工具坐标系定义与固定变换，现场左右臂及关节方向对应，以及多姿态下的 FK—EEF 一致性。本版本暂不据单一静止姿态补偿偏移，也不将显示模型用于运动控制。

## 验证与证据

- 看板及录包相关回归测试：15 项通过。
- RViz 已实际打开并检查机器人与比较连线；标记订阅确认显示 `33.5 cm / 120.0 deg`。
- 样本：`local/grid_live_review/arm_eef_alignment_latest.json`。
- 计算结果：`local/grid_live_review/arm_eef_alignment_report.json`。
- 最新本次 RViz 会话：`local/grid_live_review/session-i97qmela/`，含 `live.rviz`、状态、看板图及 `screen.png`。

上述 local 文件为本机运行产物，迁移机器时需另行保留。操作细节见[实时看板教程](../../../../tutorials/grid_live_review.md)，排查过程见[当天开发记录](2026-10-04-grid-live-review.md)。
