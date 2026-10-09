# 真机常用启动指令汇总

以下命令均在 `/home/zhoutong/omi_folder/omi_proj` 执行。每个持续运行的命令占用一个终端；保留其终端运行，按 `Ctrl+C` 停止。本页汇总现场常用入口；参数、按键和数据含义以链接的专项教程为准。

## 先确定本次运行方式

| 用途 | 动作发送端 | 配套入口 |
| --- | --- | --- |
| 独立手柄操作 | `scripts/gamepad_test.py --execute` | 机器人接收端；可同时开只读看板 |
| 人工示范采集 | `scripts/collect_rl_episodes.sh --execute` | 机器人接收端、三路传感器；脚本自己读取手柄 |
| 固定 BC 评估 | `scripts/run_bc_episodes.sh --execute` | 机器人接收端、三路传感器；脚本自己读取手柄 |
| 在线 RL | `scripts/run_async_rl.sh --execute --enable-policy` | 机器人接收端、三路传感器；脚本自己读取手柄并启动 Learner |

上述四种动作发送端**一次只运行一种**。尤其运行采集、BC 或 RL 时，不要另开 `gamepad_test.py --execute`。相机、触觉、实时看板、wrench 看板和只读预警可以各占一个终端，与所选动作入口配合。开始运动前由现场操作者确认机械臂、工具、工作空间、急停及接管方式。

## 1. 准备机器人接收端

首次配置或修改接收端代码后，在一个终端校验 SDK 资源并构建；构建本身不连接机器人：

```bash
cd /home/zhoutong/omi_folder/omi_proj
python3 scripts/import_optical_module.py verify
bash scripts/robot_controller.sh build
```

在机器人终端加载 ROS 和工作区，再连接左臂 A。`connect_on_start:=true`、`motion_authorized:=true` 和 `start_mode:=3` 会连接并切换控制模式，需在现场准备完毕后执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash

export ARM_SDK_DIR="$PWD/local/vendor/optical_module_pu/source/OpticalModule_PU/Arm_control"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ping -c 3 192.168.14.190
ros2 launch arm_delta_cmd delta_ctrl.launch.py \
  robot_ip:=192.168.14.190 \
  arm:=A \
  connect_on_start:=true \
  motion_authorized:=true \
  manual_delta_topic:=/omi/controller_test/decision \
  delta_frame:=base \
  ctrl_rate:=500.0 \
  delta_splits:=50 \
  start_mode:=3 \
  calib_mode:=measure \
  tool_xyzabc:=[5.0,0.0,200.0,-180.0,-90.0,0.0] \
  publish_root_tf:=none
```

这里将你给出的 `LOCALHOST` 发现设置改为 `SUBNET`，用于本页的网络传感器及 BC/RL 联合运行。接收端、传感器与动作进程需使用同一个 domain，并能互相发现；**修改环境变量后要重启已运行的节点**。若只做本机独立手柄测试，可在启动接收端和手柄前改用原来的设置：

```bash
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

本机独立手柄的完整流程见[机器人与手柄启动教程](robot_gamepad_startup.md)。`tool_xyzabc` 是当前示例工具参数，需与现场工具核对；`publish_root_tf:=none` 只关闭静态 TF 发布。

## 2. 分别启动三路传感器

以下每条在**不同终端**运行；每个终端先执行本段的 `cd` 和 `export`。相机与触觉脚本的 `--transport network` 会配置网络发现；外部 RealSense 使用同一 domain：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

腕部相机，输出 128×128 ROI：

```bash
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network
```

双指触觉小矩阵及六维 wrench：

```bash
bash scripts/start_daimon_live.sh tactile --transport network --tactile-wrench
```

外部 RealSense 彩色相机，在其独立终端运行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 launch realsense2_camera rs_launch.py
```

启动后确认实时策略实际订阅的外部 RGB 话题有图像；项目示例使用 `/camera/camera/color/image_raw`。如果本机 RealSense 的默认命名不同，参照[机器人与手柄启动教程的相机参数](robot_gamepad_startup.md#网络推理前启动传感器)显式设置 `camera_namespace`、`camera_name` 和彩色流。腕部和触觉话题、发布开关见[传感器命令速查](sensor_commands.md)。

## 3. 只读查看和触觉预警

下列命令各在独立终端运行，默认使用 domain 13；看板不会发布机械臂动作。

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

相机、触觉和 EEF 实时看板，以 10 Hz 更新图像面板：

```bash
bash scripts/view_grid_observation_live.sh --hz 10
```

双指六维 wrench 看板，曲线显示最近 60 秒，同时将收到的原始样本持续写盘：

```bash
bash scripts/view_wrench_live.sh --window 60
```

按 Start 采集基线的只读差值预警：

```bash
bash scripts/watch_bc_wrench.sh \
  --wrench-force-xy-warning 3.5 \
  --wrench-torque-warning 1.0
```

这两个阈值是**本次运行指定的试用值**，不是已标定的安全限值。脚本只打印预警，不会停止机器人、拦截策略动作或开启接收端触觉保护。它需要上面的触觉 `--tactile-wrench` 数据。详见[只读预警](tactile_warning.md)和[wrench 记录](wrench_live.md)。

## 4. 选择一种动作入口

以下入口在各自的新终端运行，先进入根目录并指定 domain：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

### A. 独立手柄操作

该入口只适合单独手柄操作。先按[手柄教程](robot_gamepad_startup.md)在非执行模式核对 `/dev/input/js0` 和按键，再在新终端启动：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

.venv/bin/python scripts/gamepad_test.py \
  --execute \
  --device /dev/input/js0 \
  --rate 10 \
  --home-button-code 314 \
  --scale 1 \
  --output-convention sdk-x-forward-z-left
```

按程序提示回车后开始发送；按住 RB 才发布非零手臂增量。该独立入口与下面三个采集/推理入口互斥。[完整按键、回位和夹爪说明](robot_gamepad_startup.md#5-终端-c启动手柄动作发布)。

### B. 人工示范采集

```bash
bash scripts/collect_rl_episodes.sh \
  --output "local/rl_episodes/demo_new_$(date +%Y%m%d_%H%M%S)" \
  --episode-seconds 20 --episodes 10 \
  --control-mode periodic --execute
```

每回合最长 20 秒、计划采集 10 回合，输出目录带本次启动时间。周期控制按 Start(315) 开始，RB 加摇杆进行人工动作；308 标记成功，307 提前结束。成功标签、有效 transition 和保存状态需以每回合审计为准，不能仅看目录是否生成。[采集操作与数据检查](rl_episode_collection.md)。

### C. 固定 BC 模型评估

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

从指定已有目录恢复 BC 模型，运行一个周期回合。此入口做实时网络推理和审计，**不播放训练标签，也不训练模型**。Start(315) 开始，RB 接管，308 成功，307 停止；`--resume` 继续使用该目录而不覆盖已有回合。运行前核对目录中的权重和版本。[BC 评估及标签回放的区别](bc_replay_testing.md)。

### D. 异步在线 RL

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc_demo_new_20261007_213643_rl_live_01 \
  --episodes 10 --reload-every-episodes 10 \
  --batch-size 2 --publish-every 50 \
  --execute --enable-policy
```

从指定真机会话恢复 Actor/Learner；`--enable-policy` 允许策略动作，经 `--execute` 发布到接收端。Start(315) 开始，RB 按住时人工优先，308 成功，307 停止；每 10 个完整有效回合才在回合边界检查新权重。`--episodes 10` 限定这次运行的回合数。运行前检查当前会话状态、接收端订阅以及是否有其他动作发布者。[异步 RL 操作和状态文件](async_rl.md)；[首批数据与版本边界](../docs/agent/training/chronicles/2026-10-08-first-online-rl-run.md)。

## 停止与记录

先停止当前动作入口，等待其回合审计与写盘完成，再按需停止看板和传感器，最后停止接收端。看板的关闭不会停止其他采集进程。BC/RL 日志中的“本地保存完成”不等于 Learner 已导入；RL 以运行目录的 `status.json`、`async_state.json`、`learner.log` 和 `imported.json` 核查。若实时观测、接收回执或运动异常，使用现场接管/停止流程，保留日志供复查。
