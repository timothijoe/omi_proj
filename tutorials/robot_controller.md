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

## 换机恢复

复制整个 `local/vendor/optical_module_pu/` 并 verify，或从原始 ZIP 重新导入：

```bash
python3 scripts/import_optical_module.py import /path/to/OpticalModule_PU.zip
```

导入要求目标目录不存在；不覆盖旧版本，另一个版本使用 `--destination` 指定新目录。
导入脚本只读 ZIP、复制文件、写哈希，不运行安装器、示例、厂商 SDK 或网络命令。
Python 要求3.11及以上；Humble/Python3.10机器可直接复制已验证资源，再单独重建 ROS 包。
Humble 尚未验证。完整控制契约及保留问题见[架构与接收端审计](../docs/agent/hardware/evolution/robot-controller.md)。
