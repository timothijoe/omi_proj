# OpticalModule 控制架构与接收端迁移

2026-10-05，从用户提供的 `Downloads/oct04/robot_control/OpticalModule_PU.zip` 迁入。
原包 SHA256：`f266412ad9f466966c6d75b536ffaa4eebf0b8a97dc4c85c162d275e34872112`。
原件、提取副本和逐文件清单在 `local/vendor/optical_module_pu/`；
[操作教程](../../../../tutorials/robot_controller.md)给出构建、预览与恢复方式。

## 架构落点

```mermaid
flowchart LR
    Obs[双相机 / 触觉 / EEF] --> Policy[OMI 历史策略 CUDA]
    Policy --> Arbiter[RB 手柄 / policy 仲裁]
    Arbiter --> Wrapper[换轴 / rotvec 转 SDK ABC]
    Wrapper --> Topic[/omi/action/decision]
    Topic --> Receiver[arm_delta_cmd 接收端]
    Receiver --> Hold[10Hz 名义增量换算速度 / 零指令与断流停止]
    Hold --> IK[200Hz 每周期小增量 IK 后立即下发]
    IK --> SDK[Arm_control / Marvin SDK]
    SDK --> Feedback[关节反馈 / FK 末端位姿]
    Feedback --> Obs
```

图描述当前代码接口关系；默认入口仍只启动断开的接收节点。迁移阶段未启动真机闭环，后续速度保持的软件验证不代表实机平顺度已验收。

| 原包模块 | 迁移去向和职责 |
| --- | --- |
| `omi_ws/src/arm_delta_cmd` | 维护副本在 `ros2/arm_delta_cmd`，原件仍在 local |
| `Arm_control` | local 原样保留：机器人通信、FK/IK、TCP工具、动态库及配置 |
| `omi_ws/marvin_msgs` | 完整厂商消息源在 local；运行复用项目匹配的现场 Jointfeedback 包 |
| `omi_ws/src/marvin_stand_viz` | local 保留模型、mesh、TF/关节显示桥；已有 OMI 看板继续使用现有模型 |
| `daimong_ws/src/dm_gripper*` | local 保留 ROS 夹爪/传感器包及消息，未替换 OMI 的 `omi_sensors` |
| `daimon_stuff` | local 保留夹爪、腕部相机、触觉 SDK 源码和运行资源 |
| `realsense_capture.py`、`record_data` | local 保留外部相机及录包入口 |
| `DEMO_PYTHON`、`axis_test.py`、`bag_test` | local 保留示例和原实验资料，未运行 |

## 接收端代码确认的契约

- 输入 `/omi/action/decision`：`Float64MultiArray`，六维 mm/ABC degree，无消息时间戳；
  ABC 为 `Rz(C) Ry(B) Rx(A)`。默认 A 左臂，`delta_frame=base` 即 FRAME_BASE=0。
- 手柄与策略均使用速度保持：名义增量乘以各自 `command_rate`（默认10 Hz），
  得到平移 mm/s 和 ABC degree/s；单调时钟200 Hz定时器每周期按速度除以
  `ctrl_rate` 生成小增量，做一次 IK 后立即下发。消息间隔内继续沿用最近速度。
- 新动作更新速度；全零动作立即停止。手柄 `manual_timeout` 与策略 `delta_timeout`
  默认均0.25秒，按最后有效消息的单调时间监护。`delta_splits` 为兼容保留，不再影响执行。
- `cur_joints` 初始化/切模式时取反馈，运行中取最近下发的目标，每步IK从该目标继续。
  调度延迟不补发大步；实际执行位移可能超过单条名义增量，也可能因调度延迟而偏小。
- 默认启动模式实际为 **3（关节阻抗）**，不是原文件开头注释所写的位置模式1。
  模式与 K/D 沿用迁移参数；后续已将话题执行算法改为速度保持。
- 初始化清计算侧 Tool/UserFrame；`identity` 将 TCP 设为法兰，`measure` 使用
  `tool_xyzabc`。不代表现场真实工具完成测量标定。
- 反馈50 Hz，SDK关节度转为弧度发布14维 `positions/velocities/efforts`，另一臂填零。
- EEF50 Hz，从反馈关节 FK 得到计算侧 TCP，mm转m，再左乘固定安装矩阵，
  发布 `PoseStamped` 的 xyz/xyzw、frame=`base_link`。
- A 安装矩阵为平移 `(0,0.2005,1.121)m`、旋转 `Rx(-90°)`；其旋转逆变换正是
  当前 policy wrapper 的 `(x,y,z)→(x,-z,y)`。这是代码关系核对，不能替代现场标定。
- `publish_root_tf=none` 只关闭静态 TF 发布；EEF计算仍使用写死的安装矩阵，
  并不会读取外部 TF。原代码部分注释与实际实现不一致。

## 本次迁移差异

维护副本默认不连接；连接必须另有 `motion_authorized=true`，SDK在授权后才导入，
由 `ARM_SDK_DIR` 定位，去掉 `/home/dc/...` 硬编码路径。新增关键参数有限值/范围检查、
非有限命令拒绝与连接失败清理；main 在初始化失败时也关闭 ROS context。
迁移时保留了20步算法；后续改为逐周期IK并下发，再改为手柄与策略速度保持。
话题单位保持mm/ABC degree，输入语义现为一个名义动作周期的增量。

专用构建脚本只构建接收端和匹配现场消息，产物放 local；预览固定隔离domain114且禁用反馈/TF发布。
历史 `TianjiSdkArm` 仍是另一条七关节适配路径；本接收端没有被包装成它，也未接入 SAC actor。

## 速度保持参数与停止边界

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `manual_command_rate` | 10.0 Hz | 手柄名义增量对应的频率，必须匹配发送端 `--rate` |
| `policy_command_rate` | 10.0 Hz | 策略名义增量对应的频率，必须匹配网络动作周期 |
| `ctrl_rate` | 200.0 Hz | 接收端小步IK与下发频率 |
| `manual_timeout` | 0.25 s | 手柄无有效更新时停发 |
| `delta_timeout` | 0.25 s | 策略无有效更新时停发 |
| `max_step_deg` | 2.0° | 每周期各关节目标变化限幅 |
| `envelope_radius_mm` | 100.0 mm | 相对连接时TCP锚点的球形包络，0禁用 |
| `tactile_retreat_speed_mm_s` | 2.0 mm/s | 触觉保护锁定后允许的策略Base -X后退限速 |

独立的绝对速度上限与加速度平滑尚未增加。正常手柄速度由发送端参数决定：
`--scale` 同时缩放平移和旋转速度，`--rate` 决定输入周期，两者不修改网络权重或归一化。
网络输出换算依据 `policy_command_rate`，不借用手柄scale。
IK失败、点位SDK拒绝、包络越界、无效输入及持续指令/反馈偏差会停止当前保持速度。
触觉保护默认关闭；显式开启后仍只约束策略通道，超限先停止并尝试反馈位置保持，
仅双侧触觉健康且锁定时允许限速Base -X后退。手柄沿用既有保护边界。

HIL回执的 `velocity_window_sent` 表示一个名义观察周期结束，
`velocity_hold_continues=true` 表示仍在保持速度；不是有限位移完成或物理到达信号。
`execution_confirmed=false` 保留。零速度无需等待SDK点位即可结束观察回执。
操作见[控制教程](../../../../tutorials/robot_controller.md#速度保持执行与参数)。

## 待实机核对的语义

1. ABC分量按每周期缩小并重复组合，通常不等于一次复合完整ABC旋转。
   速度保持还会改变实际执行时间，不能把网络名义增量当成反馈实际位移。
2. 策略标签来自反馈位姿，IK迭代使用命令目标；关节阻抗模式下二者会分离。
3. 每步关节限幅可能改变笛卡尔目标；包络现在在每个点下发前检查。
4. 缺反馈时仍可能下发；偏差监护在下发后检查，故障后新输入可重新启动。
   SDK发送并不证明运动完成或物理急停。
5. B臂仍需单独验收，EEF接口仍为 `/tj/info/eef_left`；TCP、安装方向与UserFrame待现场核对。

## 验证等级

速度保持阶段：接收端/触觉保护/HIL回执70项测试通过，HIL运行时16通过、1跳过。
包含真实ROS定时器配合模拟机械臂的连续发送、超过20步保持、零指令、断流、
策略触觉保护及限速撤退、手动接管、无效输入和执行回执。Jazzy两包构建成功，
安装副本与源码一致，安装入口的策略速度保持与零指令已用模拟SDK验证。
本阶段没有用实机验收SDK下发间隔、轨迹平顺度或停止距离。

以下为最初迁移阶段的历史验证：

完整原包复制及363个文件哈希复验通过，提取文件612,102,899字节。
Jazzy系统Python3.12独立构建2包成功。5项离线测试通过，覆盖默认不加载SDK、
连接授权门、假IK的20步/目标锚点/替换队列、非有限动作以及固定EEF安装变换。
设备连接、真实FK/IK动态库运行、机械臂运动、现场模式/工具标定均未验证。

隔离preview与ROS launch均实际启动并正常响应SIGINT退出，无设备连接。验证摘要保存在`local/vendor/optical_module_pu/migration-report.json`。
