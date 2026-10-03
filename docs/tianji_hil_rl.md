# 天机机械臂 HIL RL：早期控制接口调查

外部参考可用性（2026-10-03）：本页11处指向同级`cooking_proj`文件或目录的链接，
当前机器上目标不存在，保留作历史定位线索；它们不是OMI已实现或已验证的运行入口。
当前机器人回放请看[Stand方向修正版](../tutorials/corrected_stand_review.md)。

本文保留早期静态调查和初步方案，文中“下一步”等阶段性叙述属于当时计划。当前状态请以 [能力总表](capabilities.md) 和 [Agent 纪传体](agent/README.md) 为准；A 臂实验记录见 [A 臂任务与验证](a_arm_reach.md)。历史示例中的 IP、工作空间、速度和控制模式不是本项目可直接执行的配置。

## 1. 已确认的项目边界

- 目标硬件：天机 Marvin 系列机械臂，用户已选定 SDK **A 臂**。现有项目约定 A 对应左臂，现场仍须核对关节和工具映射。
- 正式项目位置：`omi_proj/`。其他目录只作为依赖或参考，本项目主流程在 OMI 开发。
- 训练基础：优先复用 [LeRobot HIL-SERL](../../hil_serl_projects/lerobot-hil-serl/) 的 SAC、actor/learner、经验池和数据集机制；用 [原版 HIL-SERL](../../hil_serl_projects/hil-serl/) 对照示范、干预和奖励流程。详细比较见 [参考项目解读](../../hil_serl_projects/docs/README.md)。
- 天机控制参考：[cooking_proj/packages/tianji_arm](../../cooking_proj/packages/tianji_arm/) 已有只读诊断、键盘/手柄点动与轨迹执行代码；[厂商 SDK](../../TJ_FX_ROBOT_CONTRL_SDK/) 提供 Python 控制与运动学接口。

## 2. 天机 SDK 的控制模型

厂商 [SDK 总览](../../TJ_FX_ROBOT_CONTRL_SDK/README.md) 把控制过程描述为：连接控制器、确认订阅数据持续更新、设置控制参数和控制状态、发送目标、完成后释放连接。它提供位置、PVT 和扭矩/阻抗等控制模式。位置模式高刚度；首期 HIL RL 应先确定经过现场验证的模式和限制，不预设“能发关节目标”就适合在线探索。

Python 包位于 [`SDK_PYTHON`](../../TJ_FX_ROBOT_CONTRL_SDK/SDK_PYTHON/)，其中 `fx_robot.py` 是控制接口，`fx_kine.py` 是 FK/IK 接口；Linux 依赖相应的 `.so`。SDK 文档要求确认 SDK 与控制器版本匹配，尤其 100343 系列协议兼容性，见 [SDK 版本说明](../../TJ_FX_ROBOT_CONTRL_SDK/README.md)。部署时要记录实机控制器版本、实际装载的动态库和运动学配置文件哈希。

### 2.1 简明式 Python 控制接口

[Python 控制 SDK 文档](../../TJ_FX_ROBOT_CONTRL_SDK/python_doc_contrl.md) 给出了 `Concise_Marvin_Robot` 的主要操作：

| 操作 | SDK 方法 | 对 OMI 的意义 |
| --- | --- | --- |
| 连接/释放 | `connect(ip)` / `release_robot()` | 会话生命周期；连接成功后仍须验证反馈在更新 |
| 读取状态 | `subscribe(DCSS())` | 返回 A/B 两臂状态和输出；需检查帧号、错误码及七关节反馈 |
| 切换位置模式 | `set_position_state(arm, velRatio, AccRatio)` | 高刚度模式，不能直接套用示例参数 |
| 切换关节阻抗 | `set_imp_joint_state(arm, velRatio, AccRatio, K, D)` | `K/D` 均是七维；需要现场验证参数与目标发送周期 |
| 下发关节目标 | `set_joint_position_cmd(arm, joint)` | 七关节角度，单位为**度**；必须验证返回值与实际反馈 |
| 停止/下使能 | `soft_stop(arm)` / `disable(arm)` | 软件停止与退出清理；物理急停另由现场安全系统提供 |
| 运动学 | `Marvin_Kine` 的 FK/IK | 可把 TCP 目标转为七关节目标，须加载正确机型配置 |

简明式接口封装了旧版 `Marvin_Robot` 的 `clear_set()`、设置字段、`send_cmd()` 序列。`cooking_proj` 的不同实验同时使用两种接口。OMI 应只选一种方式封装在设备适配层中，不让训练循环直接混用两套调用约定。

### 2.2 反馈、单位和坐标

[`arm_command_diagnostic.py`](../../cooking_proj/packages/tianji_arm/src/tianji_arm/experiments/arm_command_diagnostic.py) 从 `subscribe(DCSS())` 的 `outputs[0]["fb_joint_pos"]` 读取 A 臂七个关节角，并检查 `states[0]["err_code"]`、反馈帧是否递增。B 臂在现有点动代码中使用索引 1。该脚本限制 A 臂诊断单次动作最多 1°，执行时检查控制状态、目标和反馈，并在 `finally` 中尝试 `disable("A")` 与释放连接。这些是值得复用的防错思路，不等于已经为 RL 控制完成验收。

[`gamepad_cartesian_jog_simstyle.py`](../../cooking_proj/packages/tianji_arm/src/tianji_arm/experiments/gamepad_cartesian_jog_simstyle.py) 的 `left → SDK A`、`right → SDK B` 映射来自旧设备约定，需要现场确认。它通过 SDK FK 将关节角转换为 TCP 位姿，再将手柄速度积分为目标位姿，使用 SDK IK 求七关节角，最后发送关节目标。SDK 位姿是 `[x, y, z, a, b, c]`，平移用**毫米**、角度用**度**。其控制循环目标频率为 50 Hz；这是该示例的频率，OMI 的频率要根据 SDK、推理耗时和现场控制性能确定。

[Python 运动学文档](../../TJ_FX_ROBOT_CONTRL_SDK/python_doc_kine.md) 要求 `load_config()` 与 `initial_kine()` 使用匹配机型和目标手臂的 `.MvKDCfg`。IK 参考关节用于选择接近当前构型的解；文档特别指出第四关节参考角不能为零。OMI 必须显式检验 IK 结果有限、未超限、相邻目标不跳变，并处理无解情况。末端工具与负载也需要对应现场实物配置。

### 2.3 已有控制入口的使用价值

| `cooking_proj` 文件 | 已具备的能力 | 可提取的设计经验 |
| --- | --- | --- |
| [天机实机入门](../../cooking_proj/tutorials/tianji_hardware.md) | 只读诊断到受限单关节试动的现场流程 | 反馈/错误/帧号验证，明确执行门 |
| [键盘点动](../../cooking_proj/packages/tianji_arm/src/tianji_arm/experiments/keyboard_cartesian_jog.py) | 单步笛卡尔点动、显式工作空间、默认 dry-run | 固定工作空间、每次请求受限增量 |
| [手柄离散点动](../../cooking_proj/packages/tianji_arm/src/tianji_arm/experiments/gamepad_cartesian_jog.py) | 手柄离散点动 | 人工接管输入和 deadman 事件 |
| [手柄连续点动](../../cooking_proj/packages/tianji_arm/src/tianji_arm/experiments/gamepad_cartesian_jog_simstyle.py) | 连续 FK/IK 末端点动 | TCP 增量到关节目标的实现参考 |
| [遥操作教程](../../cooking_proj/tutorials/hardware/tianji_teleoperation.md) | 操作手册与历史连通性记录 | 参数需重新现场确认；旧记录仅证明当时可读反馈 |

`cooking_proj` 的 [真机入口清单](../../cooking_proj/tutorials/hardware/experiment_inventory.md) 还列有切菜、阻抗、轨迹播放和双臂实验。它们证明项目已有不同控制方式，但首期 RL 不应把这些复杂实验直接拼入在线 actor。

## 3. 为什么需要 OMI 自己的天机适配层

LeRobot 当前 [HIL 机器环境](../../hil_serl_projects/lerobot-hil-serl/src/lerobot/rl/gym_manipulator.py) 直接访问 `robot.bus.motors`、按 `<motor>.pos` 组装观测、调用 `robot.send_action()`，复位还直接读写总线。它默认三维末端位移动作加可选夹爪，并使用现有运动学流水线。天机 SDK 则以 A/B、七维角度（度）、控制模式和 SDK 订阅反馈为中心。因此“实现一个 LeRobot `Robot` 子类”不足以完整接通 HIL 环境；需要明确的天机环境和处理器扩展。

建议把边界定义成四层：

```text
LeRobot SAC / actor / learner / replay
              ↓
OMI Gym 环境：reset、step、reward、episode、记录
              ↓
OMI 动作仲裁与安全层：策略/人工接管 → 受限目标
              ↓
OMI TianjiAdapter：SDK 会话、反馈、控制模式、目标、停止
              ↓
天机控制器与物理急停
```

`TianjiAdapter` 只暴露无歧义的设备动作，例如 `read_state()`、`enter_control_mode()`、`send_joint_target_deg()`、`stop()`、`close()`；每次读数包含时间戳、帧号、关节反馈、控制状态和错误码。这个接口是**计划中的 OMI 设计**，不是厂商 SDK 现有类名。SDK import、A/B 索引、单位转换和异常清理都限定在此层。

当前仿真环境采用七维关节增量动作，首期任务以 TCP 距离判定成功，键盘用于逐关节点动示范。训练 transition 保存的是**最终被控制器接受的动作及其来源**，并同时记录策略原始动作、人工动作、拒绝/裁剪原因与控制状态。实机动作表示和周期仍须现场验收；策略推理和数据存储的延迟不能阻塞设备安全处理。

## 4. 第一阶段代码布局

正式代码全部写入 `omi_proj/`。已建立 `sim/`、`training/` 和 `hardware/`，并完成 A 臂仿真首期任务；相机与实机环境仍待现场信息确定：

```text
omi_proj/
  docs/                      # 设备接口、任务定义、实验和现场验收记录
  src/omi_hil_rl/
    sim/                     # 代理模型、外部天机场景 A 臂任务、键盘示范、预检与渲染
    training/                # 已有仿真 SAC、HIL 回放与逐步记录
    hardware/tianji_sdk.py   # 已有只读连接和显式授权的 SDK 适配
    tasks/                   # 待首个真实任务确定
  configs/                   # 待现场设备参数确认
  tests/                     # 已有仿真、回放和假 SDK 契约测试
```

厂商 SDK 和动态库先作为外部依赖引用，不复制进 `omi_proj` 的源码树。`cooking_proj` 的硬件环境使用 `local/vendor/SDK_PYTHON` 和 `local/vendor/tianji_test`，见 [资源清单](../../cooking_proj/manifests/local-assets.yaml)；OMI 的依赖路径应可配置，并明确实际装载版本。

## 5. 实施顺序与验收条件

1. **设备事实表。** 已选 A 臂、末端到达任务与键盘仿真示范。现场确认机型、A/左臂对应、控制器与 SDK 版本、工具/负载、可用相机及遥操作方式。保存经确认的关节限位、速度、工作空间、姿态基准和急停路径。
2. **只读适配。** 写 `TianjiAdapter.read_state()`，先用假 SDK 测试，再在现场只读连接。验收：反馈帧递增，七关节有限，状态和错误码可解释；连接断开/超时可明确报错。只读阶段不切模式、不下目标。
3. **受限控制。** 在单独执行门下验证模式切换、小幅目标、停止和清理。动作范围、速度、单步增量和工作空间都由现场配置约束；所有控制路径共用同一套限制。验收：命令响应、实际反馈及异常处置均可追踪。
4. **人工示范。** 连接遥操作、相机和 Gym 环境，先不训练。录制多回合，逐帧核对图像/关节状态/目标/实际动作/接管状态的时间对齐；可靠区分成功、失败与超时。
5. **离线与在线训练。** 在假环境先打通 LeRobot SAC actor/learner，再逐步接入实机；验证接管动作真正覆盖策略动作且进入正确经验池。[参考项目解读](../../hil_serl_projects/docs/README.md) 已指出 LeRobot 当前代码的接管标记路由风险，必须用集成测试处理。
6. **评估与奖励自动化。** 先人工标记成功；如需要，再训练奖励分类器并单独评估误报。固定任务初始条件，报告无接管成功率、完成时间、干预率、异常/停止次数和训练步数。

实体运动始终需要设备旁操作者和物理急停。`cooking_proj` 的 [安全边界](../../cooking_proj/docs/safety.md) 明确：dry-run/只读为默认，运动要有显式执行门；软件 deadman、`Ctrl+C`、`disable()` 或 `soft_stop()` 不能替代物理急停。

## 6. 仍需现场确定的具体输入

- A 臂与场景左臂的关节顺序、零位、方向和 TCP 是否一致？
- 末端到达任务在实机上的目标区域、工具和安全复位条件是什么？
- 仿真阶段使用键盘点动；现场是否需要换成低延迟手柄？
- 现场相机型号/视角、控制计算机与机器人网络连接、控制模式及被允许的频率是什么？

这些输入用于细化 `omi_proj` 的配置和接口，不妨碍先完成无硬件的适配层契约与模拟测试。

## 7. 已完成的 MuJoCo 第一轮测试

当前工作区中没有天机 Marvin MJCF/URDF，因此 OMI 最初新增 [自包含七关节代理模型](../src/omi_hil_rl/sim/assets/tianji_7dof_surrogate.xml) 和 [Gymnasium 环境](../src/omi_hil_rl/sim/tianji_surrogate.py)。代理模型采用零重力，仅模拟七个有关节限位的位置伺服轴，不包含天机真实几何或动力学。后续依据 `cooking_proj/docs` 在本机另一个检出找到了外部天机场景，完成了 [A 臂 MuJoCo 任务](a_arm_reach.md)。

环境动作是七维归一化关节增量。策略和人工接管经过同一个限位入口；`info` 同时记录策略请求、人工请求、限位后的命令动作和动作来源。观测包含七维关节位置、七维关节速度及代理 TCP 位置。临时任务是达到指定关节目标，采用稀疏成功奖励和最大步数截断；它只用于验证回合与数据流，不代表未来的实机任务。

[测试](../tests/test_tianji_surrogate.py) 覆盖：复位与 Gym 观测契约、策略动作驱动、人工接管覆盖、关节限位后动作记录、非法动作在仿真前被拒绝、超时复位、成功终止和一次带人工覆盖的完整回合。[A 臂场景测试](../tests/test_tianji_a_reach.py)在外部 MJCF 可用时检验左臂映射与任务成功。[无界面回合示例](../src/omi_hil_rl/sim/smoke.py)保留作代理接口测试。接入 LeRobot actor/learner 是后续验证。

### 7.1 仿真训练和接管记录

[训练入口](../src/omi_hil_rl/training/sim_train.py) 用 CPU 版 Stable-Baselines3 SAC 做独立仿真试验。每一步先采样策略动作，再由可配置概率的[脚本教师](../src/omi_hil_rl/sim/intervention.py)模拟接管。环境记录策略请求、人类/脚本覆盖请求、限幅后下发的目标和动作来源；[SAC 回放桥](../src/omi_hil_rl/training/executed_action_sac.py)确保经验池中是限幅和接管后的动作。[HIL 经验池](../src/omi_hil_rl/training/hil_replay.py)按配置混合接管和普通在线经验，并可对接管样本做辅助行为克隆更新。[逐步记录器](../src/omi_hil_rl/training/recording.py)将每步观测、动作、奖励和终止状态写入 JSONL。

此实现用于验证数据路径和可训练性；它不是 LeRobot HIL-SERL 的完整移植，也没有图像奖励分类器或分布式 actor/learner。键盘真人示范入口已在仿真中初始化，JSONL 可通过 `--demo-recording` 导入训练。代理任务可选进度奖励，以便早期验证策略学习；实际任务奖励要单独设计和核验。训练和评估使用 ±0.03 rad 的随机初始关节扰动。训练试验的策略、回放池及指标放在 `omi_proj/data/sim_runs/`，由 `.gitignore` 排除。

已完成的验证：在当前依赖环境下，脚本教师前 500 步持续接管，随后以 20% 概率接管；SAC 每次更新附加权重为 10 的示范行为克隆损失。训练 1500 步后，随机种子 0、1、2 的各 10 个随机初始状态评估回合均成功，平均完成步数分别为 24.6、23.4、21.7。这些数据只证明代理任务与接口闭环可工作，不能外推到真实天机机械臂。旧的纯 SAC 短试跑独立评估失败，因此当前辅助示范损失是仿真基线的重要组成部分。

### 7.2 天机 SDK 接口准备

[TianjiSdkArm](../src/omi_hil_rl/hardware/tianji_sdk.py) 已把 SDK A/B 映射、度/弧度换算、只读反馈与显式运动门封装起来。`connect()` 只连接并读取，不切控制模式；运动需要现场提供七关节限位和单步限制，显式启用 `motion_authorized`，并单独调用模式切换。对应测试使用假 SDK，不连接控制器。适配器目前尚未经过真机验收，也未接入在线训练；现场配置与首个任务明确后才能继续该部分。

此外，[MuJoCo SDK 替身测试](../tests/test_tianji_sdk_sim.py) 将同一适配器接到代理模型，覆盖以弧度输入、向 SDK 发送度数以及读回弧度反馈的完整路径。该替身不具备厂商控制器的时序、协议和故障行为，仍不能代替现场验收。

## 8. A 臂真实场景的仿真扩展

在外部天机 MJCF 上，`TianjiAReachEnv` 绑定左臂七关节、七个位置执行器和掌心 TCP，建立固定目标末端到达任务。`sim.preflight` 检查场景及任务初始化，`sim.keyboard_teleop` 记录人工逐步点动，训练/评估脚本可通过 `--scene` 运行同一 A 臂场景，`sim.visualize` 输出 PNG/GIF 与距离轨迹。运行命令、依赖资源、30 回合评估结果和可视化集中记录在 [A 臂任务与验证](a_arm_reach.md)。
