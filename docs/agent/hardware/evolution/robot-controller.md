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
    Receiver --> IK[20 次增量 IK / 关节队列]
    IK --> SDK[Arm_control / Marvin SDK]
    SDK --> Feedback[关节反馈 / FK 末端位姿]
    Feedback --> Obs
```

图描述代码接口关系；迁移没有启动该真机闭环。当前默认入口只启动断开的接收节点。

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
- 200 Hz 定时器，默认每条增量分20步；每步平移及 **ABC各分量除以20**，
  调用 `TcpForceKine.solve_tcp_delta_ik`，将关节角队列逐点送到 SDK。
- `cur_joints` 初始化/切模式时取反馈，运行中取最近下发的目标；新增量从该目标继续。
  成功解算的新队列替换旧队列，不追加排队。
- 默认启动模式实际为 **3（关节阻抗）**，不是原文件开头注释所写的位置模式1。
  本次沿用这一参数，未调整 K/D、速度或控制算法。
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
原有20步算法、话题协议、关节限幅、工作空间参数和超时行为保留。

专用构建脚本只构建接收端和匹配现场消息，产物放 local；预览固定隔离domain114且禁用反馈/TF发布。
历史 `TianjiSdkArm` 仍是另一条七关节适配路径；本接收端没有被包装成它，也未接入 SAC actor。

## 后续旋转和限幅工作需要处理的实际差异

1. **旋转拆分并不严格等价**：通常 `R(ABC/20)^20 != R(ABC)`。
   当前发送端一次 rotvec→ABC 的等价核验没有覆盖接收端重复20次的结果。
   单轴时可一致，多轴时存在差异；本次迁移没有暗中替换插补策略。
2. **动作锚点不同**：policy标签来自反馈当前位姿到未来位姿；接收端连续迭代命令目标。
   阻抗模式下指令与反馈分离会放大这种语义差异。
3. **接收端又逐关节限幅**：每子步默认2°，可能改变已完成的笛卡尔IK目标。
   原包络只查最终关节目标FK，不验完整路径；这不是上游1mm/1°限幅的等价执行。
4. 原版IK/包络失败会返回，但并不清除旧队列，且已刷新输入超时；
   缺反馈时仍可能下发，偏差保护是在下发后检查，触发后也不是锁存故障。
   这些保留行为需在后续执行器加固中处理，不能当作已通过完整安全验收。
5. 原版即使选择B臂也硬编码发布 `/tj/info/eef_left`；本次只对A臂接口建立迁移验收，
   未宣称B臂语义可直接部署。
6. EEF位置和 orientation 是绝对位姿；策略 rotation 是基坐标系旋转向量增量；
   SDK接收的是ABC增量。需要把表示、参考点、反馈锚点和20步执行放在同一条链路核对。

## 验证等级

完整原包复制及363个文件哈希复验通过，提取文件612,102,899字节。
Jazzy系统Python3.12独立构建2包成功。5项离线测试通过，覆盖默认不加载SDK、
连接授权门、假IK的20步/目标锚点/替换队列、非有限动作以及固定EEF安装变换。
设备连接、真实FK/IK动态库运行、机械臂运动、现场模式/工具标定均未验证。

隔离preview与ROS launch均实际启动并正常响应SIGINT退出，无设备连接。验证摘要保存在`local/vendor/optical_module_pu/migration-report.json`。
