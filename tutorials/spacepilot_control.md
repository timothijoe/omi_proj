# SpacePilot 机械臂末端增量控制

独立入口 `scripts/spacepilot_test.py` 复用现有手柄的接收端预检、手动话题和 SDK 坐标转换。原 `spacepilot_pose.sh` 仍只操控演示物体。当前完成离线验证和驱动只读连接，机械臂逐轴方向与手感待现场确认。

## 先预览

在项目目录执行，无需启动接收端或加载 ROS：

```bash
cd /home/zhoutong/omi_folder/omi_proj
.venv/bin/python scripts/spacepilot_test.py \
  --rate 10 \
  --translation-scale 0.5 \
  --rotation-scale 0.2 \
  --output-convention sdk-x-forward-z-left
```

默认按住 SpacePilot **实体 3（当前用户反馈 libspnav ID 19）** 才输出非零候选，松开停止。最初沿用 GUI 历史记录的 ID14，现场报告实体3输出 ID19 后已修正控制入口默认值；不同设备配置以实际事件 ID 为准。终端显示原始增量、转换后指令、启用状态及按键。该入口中实体 3 是启用键，模式通过 `--mode` 选择；与演示窗口的按键用途不同。没有夹爪或回位绑定。

设备通过 libspnav/spacenavd 接收，不使用 `/dev/input/js0`。依赖沿用本机 SpacePilot 驱动与 Tk，使用项目 `.venv` 的 NumPy 和项目模块；实际发送另需 ROS Jazzy/rclpy。无桌面 DISPLAY 也可运行此终端入口，不创建 Tk 窗口。

## 平移与旋转分别缩放

```text
平移合速度上限 = --speed-mm-s × --scale × --translation-scale
旋转角速度上限 = --rotation-deg-s × --scale × --rotation-scale
每条增量 = 输入方向和力度 × 对应速度 / --rate
```

两个基础速度默认均为 10，三个 scale 默认均为 1；scale 可取有限非负数，0 禁用对应部分。上例为 5 mm/s、2°/s；更改参数后重启程序生效。

| 参数 | 用途 |
| --- | --- |
| `--translation-scale 0.5` | 只缩放平移 |
| `--rotation-scale 0.2` | 只缩放旋转 |
| `--scale 0.5` | 在独立倍率之外，同时再乘 0.5 |
| `--mode translation` / `rotation` / `all` | 仅平移 / 仅旋转 / 六轴；默认 all |
| `--dominant-axis` | 每次仅响应力度最大的一轴，带切换滞回 |
| `--deadzone 18` | 原始输入死区，范围 [0,350)，不是手柄的 0–1 比例 |
| `--signs 1 1 1 1 1 1` | X/Y/Z/Rx/Ry/Rz 各轴反转，使用 -1 反转 |
| `--enable-button 19` | 指定启用键 ID，默认19；预览日志显示实际按钮 |
| `--enable-mode hold` / `toggle` | 按住启用（默认）/ 每次按下切换启停 |

沿用演示的前 +X、左 +Y、上 +Z 和 roll 修正。平移、旋转各自按向量范数限速，多轴满量程不会使合速度超过所设上限。SDK 出口做 `(x,y,z) → (x,-z,y)`，旋转向量转换为 ABC 后发送；不会把演示中累计的位置发送给机器人。

## 发送到现有接收端

先按[机器人接收端教程](robot_gamepad_startup.md#2-终端-a连接机器人)启动接收端，并保留其终端运行。2026-10-17现场只读探测确认：domain13/LOCALHOST不可见，domain13/SUBNET可访问接收端；下面使用该网络配置。接收端应为 `manual_command_rate=10.0`、`delta_frame=base`。停止原 `gamepad_test.py --execute` 及其他策略动作发送程序，然后在新终端执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

.venv/bin/python scripts/spacepilot_test.py \
  --execute \
  --rate 10 \
  --translation-scale 0.5 \
  --rotation-scale 0.2 \
  --output-convention sdk-x-forward-z-left
```

接收端预检通过后按回车，再按住实体 3 操控。`--topic auto` 为默认，自动读取接收端的手动话题，例如 `/omi/controller_test/decision`。执行模式要求接收端的连接/授权参数为 true，输入频率匹配且为 base 模式；预检不代替实际机器人反馈验收。

若确定发送端和接收端都在本机，可将两边改为 LOCALHOST/1；只修改 domain 不能解除 `ROS_LOCALHOST_ONLY=1` 的本机限制。修改环境变量后需重新启动受影响的程序。

启动日志现在显示本进程的 domain、localhost、discovery range 和 RMW 设置；未设置 domain 时显示默认0。反复报服务不可用时，可以在 Python 命令前加 `ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`，将配置限定于这一次运行，避免遗漏新终端的 export。

本次网络发现返回的订阅节点名为 `_NODE_NAME_UNKNOWN_`，但参数服务正常。新入口在参数检查通过后，允许配置话题各自恰有一个匿名且类型正确的订阅，启动时明确提示此匹配方式；已知错误节点、错误类型或多个匿名订阅仍拒绝。此方式校验的是服务参数及话题端点，无法证明匿名端点的节点身份；旧手柄等入口仍保留原有按节点名严格校验。

只验证某组动作时增加 `--mode translation` 或 `--mode rotation`，单轴检查可再加 `--dominant-axis`。

松开启用键、回中、输入超过 150 ms 未更新会发零；设备断连或输入会话重置会清除启用状态。控制循环停顿超过 250 ms 后丢弃旧设备连接并要求重新启用。Ctrl+C/SIGTERM/异常退出尝试发送零增量，接收端另保留自身断流停止逻辑。发送端阻塞期间无法主动发零，不能替代接收端超时或物理急停。

2026-10-17起动响应改进：从静止到首条有效非零动作时立即发送，不再等待原先10 Hz周期的剩余时间；后续从这次发送起按10 Hz继续。松键/回中仍立即发零，再次起动同样立即发送；持续运动中的方向/力度变化仍按10 Hz发送。scale、速度和换轴不变。退出旧 SpacePilot 程序并按原命令重启即可生效，无需重建或重启接收端；实际端到端时延尚未测量。

发现同一手动话题的其他发布者或策略话题发布者时退出；ROS 图发现不是分布式独占锁，仍需只运行一个动作发送入口。

实现与验收范围见[当前能力](../docs/agent/hardware/evolution/spacepilot-control.md)。

## 方向异常时只读诊断

2026-10-17用户反馈前后/左右/上下输入似乎都使机器人上下移动；原因尚未定位。先停止执行入口，使用下面的无发布诊断排除旋转和多轴混入：

```bash
.venv/bin/python scripts/spacepilot_test.py \
  --enable-button 19 --mode translation --dominant-axis \
  --translation-scale 0.5 --rotation-scale 0 --debug-input
```

按住启用键，分别向前推、向左推、向上提，每次回中后再换方向。记录各方向一行非零输出。`设备原始` 是 libspnav 的六轴值，`映射后` 是前X/左Y/上Z约定、尚未门控或缩放的输入；原始增量和最终SDK指令继续同时显示。设备原始值即使未启用也可用于观察，超过150 ms无输入会清零。

当前约定中前X转换为SDK dx，左Y转换为SDK dz，上Z转换为SDK -dy；SDK轴名不能直接当作机器人世界坐标的上下左右。若三次原始值已不同但最终指令相同，排查映射；若发出的三个轴不同而物理运动相同，需进一步核对接收端/TCP/IK及实际反馈，不能仅修改轴符号下结论。

## 起动与旋钮回中迟滞的只读记录

退出真机发送程序后运行：

```bash
.venv/bin/python scripts/spacepilot_input_check.py --seconds 30
```

按回车才开始计时。按住实体3、推动旋钮约2秒，松开旋钮后继续按住实体3约3秒，最后松开实体3，可重复两轮。工具不加载ROS、不发布动作，自动保存原始六轴、启用键事件、映射候选和零/非零状态变化到 `local/spacepilot/latency/*_input.json`；Ctrl+C可提前保存。支持 `--translation-scale`、`--rotation-scale`、`--deadzone`、`--enable-button`，默认与这次现场记录一致为1.5/0.3/18/19。

时间为本机程序读取事件的单调时钟，工具不知道手真正松开的时刻，也不测机器人运动；回中尾值或候选归零需要结合操作者动作解释。它用于区分输入残余和发送后响应，不能用无动作的采样证明运动时低延迟。

注意“立即发零”是发送端行为。本地接收端代码对普通手动零指令清除速度和 `have_goal`，停止增加目标，不会像触觉保护路径那样用当前反馈替换SDK目标。因此机械臂可能仍追踪最后目标，不能将发送零直接表述为物理立即停住；现场部署版本及其影响还需核对。

## 共用控制链的动作与反馈记录

只读入口自动加载本机Jazzy及匹配的消息overlay，不启动接收端或SDK，不发布动作：

```bash
cd /home/zhoutong/omi_folder/omi_proj
ROS_DOMAIN_ID=13 bash scripts/record_control_response.sh
```

保持已运行接收端参数不变，一次只用一个动作发送程序。记录器默认等待最多300秒，首条有效非零手动指令触发45秒记录，并保留前2秒数据；Ctrl+C可提前保存。先用手柄轻推前进约0.5秒、摇杆回中但保持RB约3秒、松开RB约2秒，重复三次，同时直接观察机械臂本体。没有足够操作空间或松开RB后仍持续移动时停止本轮。

输出在 `local/diagnostics/control_response/`，包含手动指令、关节位置/速度、EEF、回执、接收端警告及启动参数快照。`t_s` 是本机订阅回调的单调接收时间，源header另存，不能直接把跨机时钟差作为延迟。反馈使用best-effort，可能丢样。

这一轮能观察指令归零后反馈是否继续变化，但不包含完整SDK内部目标或SDK实际发送时刻，不能独自分离所有网络/SDK/动力学原因。`--trigger immediate --seconds 1` 用于不运动的入口检查；默认使用motion触发做实际响应记录。
