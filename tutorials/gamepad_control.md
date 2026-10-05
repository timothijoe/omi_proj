# 手柄控制、SDK 换轴与 RB 接管

完整实现及演进见[功能开发记录](../docs/agent/hardware/evolution/gamepad-control.md)。

## 当前使用哪个程序

现场直接控制末端用 **`scripts/gamepad_test.py`**。它读取手柄后直接发送六维增量，不订阅策略。
`python -m omi_hil_rl.real.gamepad_node` 是另一个带策略候选选择的入口；现已通过 `scripts/run_policy_gamepad.sh` 接入实时模型，见[policy 联调教程](policy_gamepad.md)。
两个入口共用手柄映射和输出 wrapper，不要同时开启动作发布。

参考发送接口为 `/home/zhoutong/Downloads/oct04/robot_pose/circle_test.py` 的最新版本。
直接手柄最终话题 `/omi/action/manual_decision`；策略选择入口将手动/RB+X 动作发到
该话题，将模型动作发到 `/omi/action/decision`。消息均为 `std_msgs/msg/Float64MultiArray`，
空 layout，默认 10 Hz。接收端触觉保护默认关闭；显式开启后只影响模型，不影响手柄。
接收端 `manual_delta_topic` 必须与手柄 `--topic`（仲裁器 `--manual-topic`）一致。
接收端决定控制哪只机械臂，消息里没有左右臂字段。

## RB + X 返回初始末端位姿

按住 RB，再按一次 X，两个入口都会读取接收端当前左臂关节反馈，并用
`eef_left` 相同的标定后 SDK FK 计算当前及以下目标关节对应的 TCP 位姿：

```text
[1.36784420538524, -1.3972774378908723, -0.8460047216729514,
 -1.4080845166192213, -0.26412765702130986, -0.1478974554847475,
 0.6224018645536978]  # rad
```

沿直线平移并插值到目标姿态，10 Hz 每步平移最多 1 mm、旋转最多 1°；
末步仅发送剩余增量，姿态限速时平移也相应减小。返回增量固定使用 SDK BASE
坐标及 ABC 度格式，不受手柄换轴、`--signs`、`--scale` 或速度选项影响。
返回期间覆盖摇杆输入；松开 RB 或断开手柄取消，重新按 X 从最新反馈重新计算。
X 一直按住不会重复触发。直接控制脚本需保持 `--rate 10`。

默认 X 使用 Linux 位置映射 `BTN_WEST=308`。终端会在按钮变化时立即显示
`RB=`、`X=`、`按下按钮=` 和 `返回=`。先在预览模式单独按 X：如果实际显示
`按下按钮=[307]`，在原启动命令中加 `--home-button-code 307`；三个手柄入口
都支持该参数。不要根据 Linux 头文件中的历史 `BTN_X` 名称推断物理 X 的键码。

接收端需使用本仓库更新后的 `arm_delta_cmd`，先在接收电脑运行
`bash scripts/robot_controller.sh build` 并重启接收节点，提供只读服务
`/delta_ctrl_node/home_poses`（`std_srvs/srv/Trigger`）。需要已连接左臂 A、
`delta_frame:=base` 和话题控制模式。服务不可用、FK 失败、请求超过 1 秒或
目标超出接收端工作空间包络时，拒绝启动返回并打印原因。
普通无 ROS 预览无法读取 FK；`gamepad_node` 的预览模式可读取服务但不发布动作。

“发布完成”仅表示增量已发完，并非实测到达确认；接收端仍可能限幅或拒绝增量。
七关节冗余臂通过末端增量返回目标 TCP 位姿，不保证七个关节角逐一等于上述值。

## 启动：跨电脑、domain 13

手柄连接在发送电脑上，在同一个终端运行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source scripts/env_ros.sh
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

# 预览：读取真实手柄、显示换轴前后值，不发送动作
python scripts/gamepad_test.py --scale 0.5 --output-convention sdk-x-forward-z-left
```

退出预览后实际发送：

```bash
python scripts/gamepad_test.py --execute --scale 0.5 \
  --output-convention sdk-x-forward-z-left
```

按回车启动发送；按住 RB 才移动，松开输出零增量，Ctrl+C 退出。
改参数或代码后应退出旧进程并重新运行。
若报 `python: command not found`，先执行 `source scripts/env_ros.sh` 激活项目 `.venv`；
本机已验证该环境可导入 rclpy、numpy 和 std_msgs，无需安装 python-is-python3。
脚本复用项目 src 模块，不是可任意单独复制走的单文件程序。

机器人接收电脑加载原本的 ROS 环境，在启动接收节点前同样设置 domain 13、允许跨机发现；
保持两台电脑网络互通，使用原本接收圆圈脚本动作的程序。已启动进程不会继承后来设置的环境变量。
接收端另一个已配置相同环境的终端可检查消息：

```bash
ros2 topic echo /omi/action/manual_decision std_msgs/msg/Float64MultiArray
```

能 echo 只证明消息到达，不代表控制器已执行。停止 circle/axis、旧手柄程序等其他同话题发布者。

## 操作映射与 scale

以下是转换前的操作坐标系，约定 +X 前、+Y 左、+Z 上。

| 按住 RB 同时操作 | 原始动作 |
| --- | --- |
| 右摇杆前/后 | +X / -X 平移 |
| 右摇杆左/右 | +Y / -Y 平移 |
| 十字键上/下 | +Z / -Z 平移 |
| 左摇杆右/左 | 绕 X 正/负旋转 |
| 左摇杆前/后 | 绕 Y 正/负旋转 |
| 十字键左/右 | 绕 Z 正/负旋转 |

摇杆死区默认 0.15，死区外线性变速，十字键固定速度。多轴同时操作限制合速度。
RB 松开或设备断连输出六个零；按住 RB 但所有控制回中也是零增量。
启用夹爪 SDK 后，A 关闭、B 张开，无需按 RB；按键设置见下节。
LB、LT/RT、X/Y、摇杆按下及 Start/Back 暂未分配。
Linux 通过内核轴/按钮语义识别当前 Xbox 手柄，默认设备 `/dev/input/js0`。

- `--scale` 同时缩放平移和旋转速度，默认 1。它**不启用坐标转换**。
- 基础速度默认 10 mm/s、10 degree/s。scale=0.5 时最大 5 mm/s、5 degree/s。
- 默认 10 Hz，因此 scale=0.5 时每步平移最多 0.5 mm，旋转向量模长最多 0.5°。
  转换后 ABC 各分量不应被误当作旋转向量模长来计算合角速度。
- 分别调速：`--speed-mm-s 5 --rotation-deg-s 2 --scale 1`。
- `--rate` 改变频率，单步增量随之换算；调度迟到不补发积压动作。
- `--signs 1 -1 1 1 1 1` 反转原始动作 Y 轴，顺序 XYZ/RxRyRz，作用在 wrapper 之前。
- `--device` 指定手柄路径，`--topic` 指定最终输出话题。

这些是请求的增量与速度，不是实际末端反馈。持续按住可持续移动，没有累计位移/工作空间限位。
零增量不替代接收端的断流停止机制；当前发送程序没有位姿反馈联锁。

## 夹爪 SDK 与 A/B 按键

直接手柄、策略选择节点及 policy 启动器均支持 `--gripper-*` 参数。
传入 `--gripper-server` 启用夹爪；不传则不连接夹爪。预览模式只打印动作，不导入或连接 SDK。
A 关闭、B 张开，与 RB 独立；启动或重连后先松开 A/B，再按一次触发一次。
长按不重复发送，同时按 A/B 不执行，需松开两个按钮后再按；SDK 工作线程忙时丢弃新按键动作。

| 参数 | 范围 / 默认值 |
| --- | --- |
| `--gripper-close-position` | 0–1000，默认 0（完全关闭） |
| `--gripper-open-position` | 0–1000，默认 1000（完全张开）；须大于关闭位置 |
| `--gripper-close-speed` | 10–100，默认 50；张开也使用此速度 |
| `--gripper-close-torque` | 10–100%，默认 **30%**；张开也使用此力矩上限 |

位置是 SDK 归一化值，速度是 SDK 档位，力矩参数是百分比上限。
SDK 使用已有行程标定初始化，不执行机械归零；每次开合先检查反馈，再设置力矩、发送目标位置。
退出时释放连接，保留当前力矩上限。夹爪命令直接通过 SDK 的 gRPC/CAN 接口发送。

厂商配置中的夹爪地址为 `192.168.14.11:55551`。
[gripper_limits.json](gripper_limits.json) 来自随包 `dm_gripper.yaml` 的标定值，使用前核对属于当前夹爪；
换夹爪后应替换为该设备的实际标定值。

在已配置 ROS 环境的项目根目录执行：

```bash
GRIPPER_SDK_DIR="$PWD/local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py"
.venv/bin/python -m pip install -r "$GRIPPER_SDK_DIR/requirement.txt"

# 先预览；实际控制时加 --execute，按回车开始
.venv/bin/python scripts/gamepad_test.py \
  --device /dev/input/js0 \
  --topic /omi/controller_test/decision \
  --scale 0.5 --output-convention sdk-x-forward-z-left \
  --gripper-server 192.168.14.11:55551 \
  --gripper-sdk-root "$GRIPPER_SDK_DIR" \
  --gripper-calibration tutorials/gripper_limits.json \
  --gripper-close-position 0 \
  --gripper-close-speed 50 \
  --gripper-close-torque 30
```

`gamepad_node` 使用 `--publish` 启用实际输出，policy 启动器使用 `--execute`；均透传上述夹爪参数。
停止其他控制同一夹爪的程序，避免不同控制入口覆盖目标。

## 输出转换模式

| `--output-convention` | 平移输出 | 旋转输出 |
| --- | --- | --- |
| `legacy`（默认） | 原坐标，mm | 原旋转向量分量，degree |
| `sdk-base-aligned` | 原坐标，mm | SDK ABC 增量角，degree |
| `sdk-x-forward-z-left` | `(x,-z,y)`，mm | 换轴后的 SDK ABC 增量角，degree |

**不传 `--output-convention` 就保持 legacy，即使 scale=1 也不转换。**

安装预设假设 SDK +X 向前、+Z 向左、+Y 向下，尚非实测标定：
平移和旋转向量都按 `(x,y,z) → (x,-z,y)` 替换分量，矩阵为 `[[1,0,0],[0,0,-1],[0,1,0]]`。
旋转向量随后转成满足 `ΔR = Rz(C) Ry(B) Rx(A)` 的 ABC 增量角。
单轴旋转等同符号/分量替换，多轴旋转不能直接将换轴后的向量当作 ABC。
只处理同一个 TCP 点的位移，不加基座原点平移偏移；左右臂不能默认安装方向相同。

接收端应按以下语义调用 SDK：

```python
ok, q_target, target = tk.solve_tcp_delta_ik(
    current_joints, data[:3], data[3:], FRAME_BASE  # 0
)
```

`current_joints` 为 SDK 要求的 degree，失败时不得使用 q_target。
需核对 UserFrame 为 identity 或与目标 Base 定义一致。wrapper 不会修改远端 SDK 设置。
若使用 FRAME_TCP，SDK 会额外按末端姿态旋转输入；固定换轴不能解决这个差异。
接收程序尚未取得，用户报告的旧版“左推导致上下移动”不能仅凭 SDK 源码确定唯一原因。

## 终端如何查看原始值与转换后值

两个入口都打印同一采样的：状态、是否已发布、原始值、转换开关/模式、是否换轴、是否转 ABC，以及最终值。
例如 scale=1、10Hz、RB 按住且右摇杆向左推满：

```text
状态=human | 已发布 | 原始(mm/deg旋转向量)=[0, 1, 0, 0, 0, 0] | 转换=是(sdk-x-forward-z-left) | 换轴=是 | 转ABC=是 | 转换后/最终(mm/degABC)=[0, 0, 1, 0, 0, 0]
```

原始值是经过死区、scale、符号配置和 RB 判断之后、换轴之前的动作，不是原始摇杆读数。
原始后三维是旋转向量，以 degree 展示；SDK 模式下最终后三维是 ABC 角。
两者的平移都以 mm 展示，便于比较；内部动作仍是 m/rad。

`转换=是` 表示本次应用了转换规则，即使零输入或 X 单轴输入导致数值相同也显示“是”。
`legacy` 显示 `转换=否`，原始/最终相同；`sdk-base-aligned` 显示转换是、换轴否、转ABC是。
“已发布”表示调用了 publish，不代表机械臂执行成功；无 --execute 时标为“仅预览”。
直接脚本每约 0.5 秒或状态变化时打印一次，策略选择节点每约 1 秒或状态变化时打印；
动作仍默认 10 Hz，打印数值为便于阅读做显示精度限制，消息使用未舍入的数值。

## 策略候选与 RL 接入边界

策略选择入口示例（需停掉直接手柄发布程序）：

```bash
python -m omi_hil_rl.real.gamepad_node --publish \
  --output-convention sdk-x-forward-z-left
```

该入口默认 10 Hz、10 mm/s、10 degree/s，调速使用 --speed-mm-s 和 --rotation-deg-s，不支持 --scale。
按住 RB 人类动作完整覆盖策略，回中仍属人工接管；松开 RB 后等待新候选，无有效候选则零增量。
断连不恢复策略；重连清除旧候选并重新读取 RB。

候选话题 `/omi/policy/candidate`，类型 `geometry_msgs/msg/TwistStamped`，depth=1、volatile。
linear/ angular 承载每个 0.1s 周期的增量 m/rad，angular 为旋转向量，均在转换前的策略坐标系；不是速度。
header.frame_id 默认 `base`，可用 --frame 改名，但改名不构成坐标转换。
header.stamp 必须是推理观测的参考 ROS 时间，采用同一时钟，不能完成旧推理后重新打时间戳。
最大年龄 0.2s，拒绝未来、非有限、重复/倒序时间和超出配置单步范围的候选；每个候选最多用一次。
释放 RB 后仅接受观测参考时间晚于释放检测时刻的候选，推理运行在独立进程。

可选 `--log local/gamepad-session.jsonl`（仅策略选择入口）：
`action_m_rad` 保存转换前 SI 动作，`original_mm_rotvec_deg` 保存显示单位的原始动作，
`output_convention` 与 `conversion_enabled` 标记转换，`command_mm_deg` 保存最终输出，
另有 source/intervention/published。日志不是反馈或已执行轨迹。

现有 stack_shadow 仍只读，无候选 producer 接入。真机 RL transition、奖励、结束条件与经验池尚未接通。
后续 actor 应记录最终选择的动作及干预标记，并明确策略空间动作与 SDK 消息的关系。

## 验证记录

最新相关测试 **67 passed**，包含坐标映射、旋转矩阵等价性、原始/最终值同采样、转换状态展示、RB 与断连行为。
早期已完成本机 Xbox 识别、ROS 预览，以及隔离 domain113 的零增量收发/空 layout/Ctrl+C 检查。
这些不代表换轴后的真机方向验收；现场结果仍待确认。
