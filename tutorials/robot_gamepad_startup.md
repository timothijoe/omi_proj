# 机器人接收端与手柄启动步骤

适用于本次 OpticalModule 控制接收端迁移后的现场验证。默认配置：ROS Jazzy、A 左臂、控制器 IP `192.168.14.190`，机器人接收端与手柄程序运行在同一台电脑。IP 不同时替换命令中的地址。

实际操作两端统一使用 `ROS_DOMAIN_ID=13` 和 `/omi/controller_test/decision`；第 1 节的离线 preview 脚本使用隔离 domain 114。本教程使用直接手柄入口，不启动策略模型。RB 键码为 311；回位键以预览中显示的实际键码为准，下方示例使用 314。

本教程的自定义话题是手动入口，接收端使用 `manual_delta_topic` 配置。
手柄执行模式默认从接收端读取该参数并自动匹配；显式传入 `--topic` 时会验证两端一致。
`delta_topic` 留给模型；触觉保护默认关闭，显式开启也不拦截手柄。

**连接启动会清错误、初始化计算侧 TCP，并切入模式 3（关节阻抗），不是只读连接。** 按现场规程完成机器人上电，确保工作空间无人、急停可用。迁移目前完成离线验证，实际安装方向、TCP 和真机执行仍需现场验收。

## 1. 校验资源、构建并离线预览

新开终端，不进入训练 venv，也不要加载旧的 `scripts/env_marvin.sh`：

```bash
cd /home/zhoutong/omi_folder/omi_proj
python3 scripts/import_optical_module.py verify
bash scripts/robot_controller.sh build
```

两步成功后启动离线预览：

```bash
bash scripts/robot_controller.sh preview
```

看到 `delta_ctrl_node 启动` 后按 `Ctrl+C` 退出。preview 不导入厂商 SDK、不连接设备，也不发布反馈。

更新 RB+X 功能后，需要在机器人接收端电脑执行上述 build，并退出、重启旧接收节点；只重启手柄程序不会让旧接收节点提供新的 FK 服务。

## 2. 终端 A：连接机器人

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash

export ARM_SDK_DIR="$PWD/local/vendor/optical_module_pu/source/OpticalModule_PU/Arm_control"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

ping -c 3 192.168.14.190
```

确认电脑可访问控制器，再启动接收端：

```bash
ros2 launch arm_delta_cmd delta_ctrl.launch.py \
  robot_ip:=192.168.14.190 \
  arm:=A \
  connect_on_start:=true \
  motion_authorized:=true \
  manual_delta_topic:=/omi/controller_test/decision \
  delta_frame:=base \
  ctrl_rate:=200.0 \
  delta_splits:=20 \
  start_mode:=3 \
  calib_mode:=measure \
  tool_xyzabc:=[5.0,0.0,200.0,-180.0,-90.0,0.0] \
  publish_root_tf:=none
```

上述命令使用 `calib_mode:=measure`，根据 `tool_xyzabc` 初始化计算侧工具 TCP；这些参数需与现场工具一致，初始化成功本身不代表已完成实测标定。改成 `calib_mode:=identity` 时 TCP 与法兰重合。`publish_root_tf:=none` 仅关闭静态 TF 发布，EEF 计算仍使用代码中的固定安装矩阵。

正常日志应包含：

- `机械臂当前关节角`
- `TCP 标定成功 (mode=measure)`：与上方命令对应，仅表示计算初始化成功。
- `机械臂连接成功, 当前模式: 关节阻抗`
- `delta_ctrl_node 启动`

如果出现 UDP 未刷新、FK 失败或模式切换失败，停止验证并保存完整日志。保持此终端运行。

## 3. 终端 B：检查机器人反馈

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash

export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

ros2 topic echo /tj/info/joint_feedback --once
ros2 topic echo /tj/info/eef_left --once
ros2 service list | grep home_poses
ros2 topic hz /tj/info/joint_feedback
```

关节反馈目标频率约 50 Hz，关节位置单位 rad。EEF 位置单位 m，包含固定安装变换。核对反馈与实际姿态是否合理；按 `Ctrl+C` 结束频率检查。

服务检查应输出 `/delta_ctrl_node/home_poses`。如果没有输出，先检查接收端是否已构建并重启、是否加载本仓库的 install 环境，以及两端是否同为 domain 13。这里使用系统通常自带的 `grep`，无需安装 `rg`；也可直接执行 `ros2 service list` 查看全部服务。

需要验证 FK 服务时，可执行以下只读请求，它不会下发运动：

```bash
ros2 service call /delta_ctrl_node/home_poses std_srvs/srv/Trigger '{}'
```

成功时返回 `success: true` 和当前、目标 TCP 位姿矩阵；`success: false` 时按 `message` 排查连接、左臂 A、BASE 话题控制模式或工作空间包络。

## 4. 终端 C：连接手柄并预览

接上手柄，在新终端执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"

export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

ls -l /dev/input/js*

.venv/bin/python scripts/gamepad_test.py \
  --device /dev/input/js0 \
  --rate 10 \
  --home-button-code 314 \
  --scale 1 \
  --output-convention sdk-x-forward-z-left
```

设备编号不同时修改 `--device`。本入口使用项目 `.venv/bin/python`：本机该环境已有 gymnasium 1.3.0，已验证 gymnasium、rclpy、std_msgs 导入及脚本 `--help`。使用 `/usr/bin/python3` 会因缺少 gymnasium 报错。

预览不会发送 ROS 话题或动作，即使输出为 `human`。检查状态：

- 未按 RB：`idle`，输出六个零。
- 按住 RB 并操作：`human`，显示转换前后数值。
- 单独按 X：核对 `X=True` 和实际 `按下按钮` 键码；RB+X：同时显示该键码与 311。若 `X=False`，将实测键码传给 `--home-button-code`。普通预览无 ROS 节点，RB+X 会提示 FK 服务不可用；此模式用于核对按键，不计算或发布返回轨迹。
- `disconnected`：按同行错误检查设备、权限或手柄兼容性。

确认后按 `Ctrl+C` 退出预览。

## 5. 终端 C：启动手柄动作发布

确保没有其他手柄、policy、circle 或 axis 动作发送程序运行。下面包含完整环境配置，可在新终端直接复制执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

.venv/bin/python scripts/gamepad_test.py \
  --execute \
  --device /dev/input/js0 \
  --rate 10 \
  --home-button-code 314 \
  --scale 1 \
  --output-convention sdk-x-forward-z-left
```

启动时先查询接收端的连接授权参数和实际手动订阅话题；查不到、接收端未连接或订阅不匹配时会报错退出。若要指定话题，可加 `--topic /omi/controller_test/decision`，与接收端配置不同会报错。

**按回车开始发送，按住 RB（右肩键，不是 RT 扳机）并操作才产生非零增量。** 默认 10 Hz，当前请求速度上限为平移 10 mm/s、旋转 10°/s；这些是指令值，不是实际反馈速度。

| 按住 RB 同时操作 | 转换前动作（约定 +X 前、+Y 左、+Z 上） |
| --- | --- |
| X | 返回指定初始末端位姿，10 Hz 每步最多 1 mm；松开 RB 取消 |
| 右摇杆前／后 | +X／−X 平移 |
| 右摇杆左／右 | +Y／−Y 平移 |
| 十字键上／下 | +Z／−Z 平移 |
| 左摇杆右／左 | 绕 X 正／负旋转 |
| 左摇杆前／后 | 绕 Y 正／负旋转 |
| 十字键左／右 | 绕 Z 正／负旋转 |

命令启用了 `(x,y,z) → (x,-z,y)` 换轴和旋转向量到 SDK ABC 的转换，与接收端 `delta_frame:=base` 配套。实际物理方向尚待验收，首次逐轴短时测试平移，再检查单轴旋转。多轴 ABC 分步执行与目标旋转的严格等价性仍未解决。

松开 RB、手柄断连或控制回中时发送零增量。本入口不订阅策略，松开 RB 不会恢复策略动作。

### RB + X：返回固定初始末端位姿

1. 按回车开始发送，先松开 X，保持摇杆回中。
2. 持续按住 RB，再按一下 X；只需点按 X，返回过程中保持 RB 按住。
3. 松开 RB 或手柄断开会取消返回；重新按 X 从最新反馈重新计算。长按 X 不重复触发。

返回先读取当前左臂关节反馈，然后使用与 `eef_left` 相同的标定后 SDK FK，计算当前及以下固定关节角对应的 TCP 位姿：

```text
[1.36784420538524, -1.3972774378908723, -0.8460047216729514,
 -1.4080845166192213, -0.26412765702130986, -0.1478974554847475,
 0.6224018645536978]  # rad，左臂 7 个关节
```

返回时覆盖摇杆输入，以 10 Hz 发布位姿增量，平移每步最多 1 mm、旋转每步最多 1°，末步只发送剩余量。姿态限速时平移也相应减小。返回固定使用 SDK BASE 坐标系及 ABC 度格式，因此日志中的 `换轴=否`、`sdk-base-aligned` 是预期行为。返回速度不受普通手柄的 `--scale 0.5` 影响。

| 输出 | 含义与处理 |
| --- | --- |
| `X=True`、`按下按钮` 同时包含回位键码与 311 | 当前手柄已正确识别 RB+X |
| `home_waiting` | 正在读取当前关节并计算 FK |
| `human_home` | 正在发送返回增量 |
| `home_unavailable`、FK 服务不可用 | 按第 1–3 节构建、重启接收端并检查服务；此时发送六个零，不会返回 |
| `home_failed` | 查看 `返回=` 中的超时、FK 或控制模式等失败原因 |
| 目标超出包络 | 接收端拒绝目标；核对目标与现场工作空间配置 |
| 返回增量发布完成 | 仅表示增量已发完，不代表实测到达 |

七关节冗余臂通过末端增量返回目标 TCP 位姿，不保证七个关节角逐一等于给定值。详细行为见[RB+X 返回说明](gamepad_control.md#rb--x-返回初始末端位姿)。

程序有默认回位键码；本教程的 314 是待预览核对的示例。换手柄时重新在预览模式检查键码。Shell 多行命令每行末尾仅保留一个 `\`，不要输入 `\ \`。

### 同时启用夹爪：A 关闭、B 张开

直接手柄入口 `scripts/gamepad_test.py` 现在默认启用项目夹爪配置：
地址 `192.168.14.11:55551`、项目自带夹爪 SDK、`tutorials/gripper_limits.json`。
原先省略 `--gripper-server` 会静默忽略 A/B；现在普通手柄启动命令也支持 A/B。
仅控制机械臂时加 `--no-gripper`；预览模式仍不连接或驱动夹爪。
启动后会显示夹爪地址和模式。更改代码后退出旧手柄进程，再重新运行原命令；
当前进程不会自动加载新代码。下方完整命令仍可用于显式指定设备配置。

先退出正在运行的手柄程序，停止其他控制同一夹爪的程序。
以下地址 `192.168.14.11:55551` 和 [gripper_limits.json](gripper_limits.json) 中的标定值来自随包配置，
使用前确认对应当前夹爪；换设备后替换地址及实际标定值。初始化使用已有标定，不执行机械归零。

在新终端运行以下完整命令，或在终端 C 使用相同环境重新启动：

```bash
cd /home/zhoutong/omi_folder/omi_proj

source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

.venv/bin/python scripts/gamepad_test.py \
  --execute \
  --device /dev/input/js0 \
  --topic /omi/controller_test/decision \
  --rate 10 \
  --home-button-code 314 \
  --scale 1 \
  --output-convention sdk-x-forward-z-left \
  --gripper-server 192.168.14.11:55551 \
  --gripper-sdk-root "$PWD/local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py" \
  --gripper-calibration tutorials/gripper_limits.json \
  --gripper-close-position 0 \
  --gripper-close-speed 50 \
  --gripper-close-torque 30
```

**按回车开始，先松开 A/B/X，再按键操作。** 此命令同时支持 RB+X 返回和 A/B 夹爪控制。

| 按键 | 夹爪动作 |
| --- | --- |
| A | 关闭：目标位置 0，速度 50，力矩上限 30% |
| B | 张开：默认目标位置 1000，使用相同速度和力矩上限 |

夹爪无需按 RB，机械臂移动仍需按住 RB。长按 A/B 只触发一次；同时按下不执行动作，
需松开两个按钮后再按。启动或手柄重连后也需先松开 A/B。

- `--gripper-close-position`：0–1000，0 为完全关闭；须小于张开位置。
- `--gripper-open-position`：0–1000，默认 1000（完全张开）。
- `--gripper-close-speed`：10–100，默认 50，是 SDK 速度档位。
- `--gripper-close-torque`：10–100%，默认 **30%**，是力矩上限。

改参数后退出旧进程并重新启动。去掉 `--execute` 可先预览按键和夹爪目标，不连接设备或发送动作。
本机已安装夹爪 SDK 依赖；换机或遇到 `No module named 'grpc'` 时执行：

```bash
.venv/bin/python -m pip install -r \
  local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py/requirement.txt
```

更多接口细节见[夹爪 SDK 配置与启动示例](gamepad_control.md#夹爪-sdk-与-ab-按键)。

## 6. 停止

1. 松开 RB 和 A/B，在终端 C 按 `Ctrl+C` 退出手柄程序；启用夹爪时同时释放夹爪 SDK 连接，保留当前力矩上限。
2. 在终端 A 按 `Ctrl+C` 退出接收端，程序释放 SDK 连接。
3. 按现场规程停止机器人。

零增量、程序退出和释放 SDK 连接均不等于物理急停或确认已下使能。异常运动时使用物理急停；原接收端故障和队列保护仍有待完善。

## 跨电脑运行

如果手柄程序与机器人接收端运行在不同电脑，两台电脑需网络互通。所有相关终端在启动程序前统一改为：

```bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

重新启动已运行的接收端和发送端，环境变量不会自动影响现有进程。两端话题仍保持 `/omi/controller_test/decision`。同机使用的 localhost 设置只限制 ROS 发现，不阻止 SDK 访问控制器 IP。

## 常见问题与参考

### 2026-10-05 功能修改与现场排查记录

- 新增两个手柄入口共用的 RB+X 返回逻辑，以及接收端只读 FK 服务 `/delta_ctrl_node/home_poses`；默认动作频率保持 10 Hz。
- 增加 `--home-button-code`，并在按键或返回状态变化时立即打印键码、`RB=`、`X=` 和 `返回=`。现场已确认 X=307、RB=311，启动命令已统一加入 `--home-button-code 307`。
- 现场日志已确认 RB+X 正确触发，但返回因 FK 服务不可用而未启动；该日志不代表已完成真机返回验证。启动步骤增加构建后重启接收端、加载新 install 环境和服务检查。
- 服务检查由 `rg` 改用 `grep`，避免现场缺少 ripgrep 导致 `BrokenPipeError`。

### 手柄速度保持与 10 Hz

手柄发送端仍使用 `--rate 10`。接收端的 `manual_delta_topic` 使用速度保持：
每条 `[dx,dy,dz,dA,dB,dC]` 增量乘以 `manual_command_rate`（默认 10 Hz）
换算为 mm/s、degree/s；200 Hz 控制循环每周期执行速度除以 `ctrl_rate` 的小增量，
做一次 IK 并立即下发。手柄消息略晚到时继续沿用最近速度，不再因 20 步耗尽而停顿。
`delta_splits` 为兼容保留，不再影响手柄或策略话题的速度。

松开 RB、摇杆回中、断开手柄或切换通道后，发送端的全零消息立即停止速度保持。
若零消息丢失或发送端退出，接收端在 `manual_timeout`（默认 0.25 秒）未收到有效更新后停发，
该期限使用单调时钟，独立于 ROS 时间。IK 失败、包络越界、SDK 点位拒绝或持续反馈偏差
也停止当前速度保持。原有手动输入与策略触觉保护的边界保持不变。

接收端新增 launch 参数：

```text
manual_command_rate:=10.0
manual_timeout:=0.25
policy_command_rate:=10.0
delta_timeout:=0.25
```

`manual_command_rate` 必须与发送端 `--rate` 一致。不要通过改变此参数调速度；
速度仍由发送端 `--scale` 和速度参数决定。若调整发送频率，同时调整断流期限；
RB+X 返回目前仍要求发送端使用 10 Hz。

修改接收端后执行 `bash scripts/robot_controller.sh build`，然后退出并重启接收节点。
无需改变现有话题或手柄启动命令。控制循环按标称 5ms 生成小步，调度延迟不会补发大步；
这消除了队列衔接停顿，但操作系统和 SDK 的实际下发间隔仍需实机测量。

### 其他问题

- `ModuleNotFoundError: No module named 'gymnasium'`：使用本教程的 `.venv/bin/python`，不要使用系统 `/usr/bin/python3` 启动手柄。若换机后的项目 venv 尚未安装该依赖，执行 `.venv/bin/python -m pip install 'gymnasium>=1,<2'`。
- 能收到动作消息但机器人不动：检查接收端连接日志、两端 domain 与话题，以及是否按住 RB。消息到达不代表控制器执行成功。
- 换机仅 clone 仓库不足以获得 SDK：另带 `local/vendor/optical_module_pu/` 或重新导入原 ZIP，再重新构建。

相关文档：[控制接收端迁移与恢复](robot_controller.md)、[手柄映射与输出转换](gamepad_control.md)、[接收端契约与遗留问题](../docs/agent/hardware/evolution/robot-controller.md)。

### 策略速度保持

神经网络输出话题 `/omi/action/decision` 同样采用速度保持：
增量乘以 `policy_command_rate`（默认 10 Hz）换算为速度，200 Hz 每周期做一次 IK 并下发。
该参数必须与策略动作周期一致，不用于调网络 scale。网络输入、权重及动作归一化不变。
最近速度保持到新动作、零动作、保护触发或 `delta_timeout` 断流（默认 0.25 秒）。
消息迟到时实际位移可能超过单条名义增量；调度延迟不补发大步。
策略继续受触觉保护约束，受保护后退限速为 `tactile_retreat_speed_mm_s`。

HIL 接受回执标记 `control_mode=velocity_hold` 和 `nominal_duration_s`。
经过一个名义动作周期后发出 `velocity_window_sent` 回执：`finished=true` 代表
控制观察窗口结束，`velocity_hold_continues=true` 表示保持仍在继续；
不代表请求位移已经完成，`execution_confirmed` 仍为 false。
零速度指令立即完成回执，不等待运动点位。相邻策略动作无需等待队列耗尽。
