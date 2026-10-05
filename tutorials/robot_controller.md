# OpticalModule 机械臂控制代码迁移

2026-10-05：用户提供 `OpticalModule_PU.zip`。已保留完整原包、提取源文件与资源，
将机械臂接收端迁入 `ros2/arm_delta_cmd`，完成本机 Jazzy 构建与离线检查。
本次没有连接控制器、切换机械臂模式或发布真机动作。

## 文件位置

| 位置 | 内容 |
| --- | --- |
| `ros2/arm_delta_cmd/` | 项目维护的 ROS 接收端、launch 和包描述 |
| `ros2/live_feedback_interfaces/marvin_msgs/` | 接收端匹配的现场关节消息，复用已有源码 |
| `local/vendor/optical_module_pu/OpticalModule_PU.zip` | 完整原始归档，包含原来的构建产物 |
| `local/vendor/optical_module_pu/source/OpticalModule_PU/` | 提取的源码、SDK、配置、模型及示例 |
| `local/vendor/optical_module_pu/provenance.json` | 来源、原包及363个提取文件的 SHA256 |
| `local/vendor/optical_module_pu/migration-report.json` | 本次维护副本与原文件的哈希对应 |
| `local/ros2/robot_controller_ws/` | 本机独立 build/install/log |

提取副本排除了 `.git`、build/install、缓存、日志和编辑器配置；完整 ZIP 保留所有原件。
机械臂 SDK 的 `.so` 是 x86-64；不能直接在 ARM 控制机上使用。
原包中的 ROS 构建产物混有其他平台/Python 版本，运行时只加载本机重新构建的 overlay。
原始厂商许可证未明确，保留原有声明，不将 SDK、模型和二进制加入 Git。

## 构建与离线启动

接收端[USB 插入触觉保护](tactile_guard.md)默认关闭，显式开启后只约束模型通道。
模型超限锁定后只允许限速 Base -X 撤退，断流/无效触觉时禁止全部模型动作。
手柄发送独立 `manual_delta_topic`（默认 `/omi/action/manual_decision`），键盘也不受
触觉保护影响；原有 IK/包络/关节限制仍保留。启用保护要求 `delta_frame=base` 并显式采集基线。

使用安装了 ROS Jazzy、colcon、rosidl、rclpy、std_msgs、std_srvs、geometry_msgs、tf2_ros
的系统 Python。不要在训练 venv 或加载过历史 `marvin_msgs` 的终端构建。

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/robot_controller.sh build
bash scripts/robot_controller.sh preview
```

`preview` 固定 localhost/domain114，订阅隔离话题 `/omi/controller_preview/decision`，
不导入机械臂 SDK，不连接设备，不发布关节、EEF 或安装 TF。Ctrl+C 结束。
它验证 ROS 节点装配，不提供模拟 IK；收到增量会因未连接而丢弃。
脚本不接收额外参数，避免无意覆盖离线配置。

迁移节点直接运行时也默认 `connect_on_start=false`、`motion_authorized=false`。
未来现场启动必须同时显式启用两项，并设置 `ARM_SDK_DIR` 到上述源目录的 `Arm_control`。
连接过程会清错误、加载 Tool/UserFrame 并切控制模式，因此不能作为只读连接入口。
本次不将该控制端自动接到 `run_policy_gamepad.sh`；两者仍是独立进程。

验证命令（新终端）：

```bash
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export ROS_DOMAIN_ID=114 ROS_LOCALHOST_ONLY=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q tests/test_robot_controller_migration.py
python3 scripts/import_optical_module.py verify
```

**不要加载 `scripts/env_marvin.sh` 的旧录包消息替代此 overlay**：旧定义是
`arm_positions/body_positions/head_positions` 等字段，接收端使用固定14维
`positions/velocities/efforts`。同名 `marvin_msgs/Jointfeedback` 不代表线协议兼容。

## 速度保持执行与参数

手柄和神经网络话题现在都执行速度保持，不再按有限20步队列结束动作。
话题仍为六维名义增量 `[dx,dy,dz,dA,dB,dC]`，单位mm/ABC degree：

```text
期望速度 = 名义增量 × 输入频率
每控制周期增量 = 期望速度 / ctrl_rate
```

例如10Hz输入的单轴0.5mm增量对应5mm/s；200Hz每步为0.025mm。
每周期从最近已下发关节目标出发，IK、限幅、包络检查后立即下发。
新消息更新速度，消息间隔内保持最近速度。消息晚到时实际位移可能大于名义增量；
调度延迟不放大步长补偿。尚未增加独立速度上限或加速度平滑。

| 接收端参数 | 默认值 | 用途 |
| --- | --- | --- |
| `manual_command_rate` | 10.0 | 手柄输入频率，匹配发送端 `--rate` |
| `policy_command_rate` | 10.0 | 网络动作频率，匹配策略实际动作周期 |
| `ctrl_rate` | 200.0 | 每秒小步IK和下发次数 |
| `manual_timeout` | 0.25 | 手柄无有效更新的停止期限，秒 |
| `delta_timeout` | 0.25 | 策略无有效更新的停止期限，秒 |

`delta_splits`仅为兼容保留，不再影响任一话题的速度或时长。
`--scale`只缩放直接手柄的平移与旋转速度，不改变网络scale、归一化或权重。
全零指令立即停止；发送端松开RB、回中或断开后发零，零消息未到则由断流期限停发。
两个断流期限均使用单调时钟，控制定时器也不依赖ROS时间跳变。
IK失败、SDK点位拒绝、包络越界、非有限输入及持续反馈偏差会停止当前保持。
策略仍受显式启用的触觉保护约束，锁定后允许的Base -X撤退速度默认不超过2mm/s。
手柄与键盘沿用原有触觉保护旁路；更换输入源时速度状态相应替换。

### 更新安装版本并重启

源码修改不会自动更新正在运行的Python进程。先停止手柄和策略发布端，再退出旧接收节点：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/robot_controller.sh build
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
```

随后按[现场启动教程](robot_gamepad_startup.md#2-终端-a连接机器人)的原接收端命令重新启动，
如需显式配置，在launch命令中使用：

```text
manual_command_rate:=10.0 manual_timeout:=0.25
policy_command_rate:=10.0 delta_timeout:=0.25 ctrl_rate:=200.0
```

不要同时运行新旧接收端。接收端启动日志会显示两路话题、输入频率及断流期限。
手柄保持`--rate 10`，RB+X返回目前也要求10Hz。
若显式传入其他`delta_timeout`，该值覆盖默认0.25秒。
A/B夹爪在直接手柄入口默认启用项目配置；原手柄命令重启后可用，
`--no-gripper`关闭，详见[夹爪操作](robot_gamepad_startup.md#同时启用夹爪a-关闭b-张开)。

### HIL回执和验证边界

`velocity_window_sent`的`finished=true`表示一个名义控制观察周期结束；
`velocity_hold_continues=true`表示保持还在继续，不是物理到达或有限位移完成。
`execution_confirmed=false`保留；零速度回执无需发送运动点位。
详见[HIL教程](hil_actor_learner.md#速度保持执行回执)。

接收端/保护/HIL回执70项测试通过，HIL运行时16通过、1跳过。
安装入口和真实ROS定时器使用模拟机械臂验证，未进行本阶段实机平顺度或停止距离验收。

## 换机恢复

复制整个 `local/vendor/optical_module_pu/` 并 verify，或从原始 ZIP 重新导入：

```bash
python3 scripts/import_optical_module.py import /path/to/OpticalModule_PU.zip
```

导入要求目标目录不存在；不覆盖旧版本，另一个版本使用 `--destination` 指定新目录。
导入脚本只读 ZIP、复制文件、写哈希，不运行安装器、示例、厂商 SDK 或网络命令。
Python 要求3.11及以上；Humble/Python3.10机器可直接复制已验证资源，再单独重建 ROS 包。
Humble 尚未验证。完整控制契约及保留问题见[架构与接收端审计](../docs/agent/hardware/evolution/robot-controller.md)。
