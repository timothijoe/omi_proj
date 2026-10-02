# HIL 训练与数据流

本文是训练能力的当前事实入口，涵盖干预、奖励、策略更新和经验池。实现为 CPU PyTorch + Stable-Baselines3（SB3）SAC 单进程仿真，尚未接入 LeRobot 分布式 actor/learner。A 臂任务定义见 [模型与任务](../../simulation/evolution/model-and-task.md)，操作命令见 [训练教程](../../../../tutorials/a_arm_simulation.md)。

## 架构与入口

`training.sim_train` 显式收到 `--scene` 时创建 A 臂 TCP 到达环境，否则创建代理关节目标环境。仅设置 `OMI_TIANJI_SCENE` 不会使训练入口自动选择 A 臂，仍需传 `--scene`。环境包装顺序为 `TransitionRecorder(ScriptedInterventionWrapper(base))`，学习器为 `DemoRegularizedSAC`，默认经验池为内存 `HILReplayBuffer`；`--replay-backend disk` 选择 [磁盘后端](disk-replay.md)，保持相同采样与动作语义。

一步数据流：

```text
观测 → 策略动作（预热阶段为随机动作）
                 ↓
        教师或人工覆盖 → 关节目标限位 → MuJoCo
                                           ↓
                         奖励、下一观测、结束信号
                                           ↓
                     JSONL + 最终命令动作进入经验池
                                           ↓
                        双流采样 → SAC 更新 → 新策略
```

策略输入是七关节位置和速度、TCP 位置和目标位置，共 20 个数值；输出为七维 `[-1,1]` 归一化关节增量。当前不使用图像输入。

## 1. 干预与动作仲裁

**脚本干预。** `ScriptedInterventionWrapper.step()` 每步按概率选择是否接管；教师读取当前关节角，以 `clip((goal_rad-current_rad)/max_delta_rad, -1, 1)` 生成七维动作。它知道预设目标关节构型，属于仿真教师，不是人类输入或学到的策略。`InterventionSchedule` 在每个环境步后调整下一步的接管概率。最近验证配置是前 500 步全部接管，之后以 0.2 概率接管，共记录 709 个教师步。

**键盘干预。** `sim.interactive_rollout` 加载已有策略，每步显示建议并等待输入：回车执行策略，`1+..7-` 将整个七维动作替换为对应的单关节点动，`h` 替换为全零增量；`r` 复位，`q` 退出。这个入口运行和录制策略，不在线更新策略。`sim.keyboard_teleop` 可单独录制示范，再由训练的 `--demo-recording` 导入。真人连续输入尚未接入 `sim_train`。

**共同执行入口。** 环境 `step(action, intervention_active=True, human_action=...)` 选人工/教师动作，否则选策略动作；覆盖是整步替换，没有按轴混合或加权。请求经过同一关节限位路径：

```text
target = clip(current + requested * 0.04 rad, joint_limits)
executed_action = (target - current) / 0.04 rad
```

向七个 MuJoCo 位置执行器下发 `target`，推进 0.1 s 的仿真。`info` 保留 `policy_action`、可选 `human_action`、`executed_action`、`commanded_joint_target_rad` 和 `action_source`。`ExecutedActionSAC._store_transition()` 将 SB3 原提议动作替换为 `executed_action` 后入池。这里执行动作是**限位后的命令增量**，不是测得的实际关节位移。`human` 标签同时用于脚本教师和真人输入，目前不能只凭该标签区分两者。

## 2. 奖励与回合结束

训练入口固定创建 `reward_mode="progress"` 环境。A 臂任务以世界坐标下 TCP 到目标的欧氏距离 `d`（米）计算：

```text
reward = 10 * (distance_before - distance_after) - 0.01 + float(terminated)
```

靠近目标获得正的进度奖励，远离目标获得负的进度奖励；每步扣 0.01；成功步额外加 1。例如从 0.10 m 接近到 0.08 m 且未成功，该步奖励为 0.19。策略动作和干预动作使用相同奖励公式。

A 臂 TCP 误差不超过 0.035 m 时 `terminated=True`；最多 80 步，达到上限且未成功时 `truncated=True`。目标来自预设构型的正运动学，是当前模型内的固定可达点。训练与独立评估均使用 ±0.03 rad 的初始关节扰动。

`sim_eval` 和训练中的周期评估使用新建环境的默认 `reward_mode="sparse"`：成功为 1，其他步为 0；无接管、确定性策略推理。因此评估的 `mean_return` 是稀疏奖励回报，不能与训练进度奖励的回报直接比较。代理关节任务的进度距离是关节误差范数，成功用最大单关节误差判定；它仅用于接口验证。

当前没有图像奖励分类器、人工成功按钮、碰撞惩罚、力约束奖励或平滑惩罚。离线示范导入保留 JSONL 原有 `reward`，不会自动改成进度奖励；录制与训练使用不同奖励模式时需要另行核查数据语义。

## 3. SAC 与可选行为克隆更新

标准 SAC 由 SB3 执行。两个 Critic 用经验中的最终命令动作学习带目标网络的 Bellman 值；Actor 使用当前策略采样动作，最小化 `mean(alpha * log_prob - min(Q1, Q2))`；温度 `alpha` 自动更新。七维动作下 SB3 自动目标熵为 -7。目标 Critic 通过软更新跟随当前 Critic。

| 参数 | 当前训练实现 |
| --- | --- |
| 网络 | `MultiInputPolicy`；Actor/Critic 隐藏层 `[64, 64]` |
| 开始学习 | `min(100, max(1, steps // 4))` 个环境步后 |
| Batch | 64；默认在线/示范各 32 条 |
| 更新频率 | `train_freq=1`、`gradient_steps=1`，开始学习后每个环境步一次 SAC 更新 |
| 学习率、折扣、软更新 | SB3 2.9.0 默认：`3e-4`、`gamma=0.99`、`tau=0.005` |
| 初始熵系数 | CLI `--entropy-initial`，默认 1.0；最近验证使用 0.01，之后自动学习 |
| BC 权重 | CLI `--bc-weight`，默认 10；最近纯 SAC 验证使用 0 |

`DemoRegularizedSAC.train()` 先执行 SAC 更新；当 BC 权重大于零且示范流非空时，再独立抽取示范批次，以 `bc_weight * MSE(actor_deterministic(obs), executed_action)` 做一次额外 Actor 优化。它不代替 SAC 更新，也不改变奖励。当前入口每次调用仅有一次 SAC 梯度更新；BC 计数统计额外优化次数。

最近的 1500 步实验有 1400 次 SAC 更新、0 次 BC 更新。关闭 BC 仍使用教师示范和接管数据，不能解释为没有示范的普通 SAC。默认熵纯 SAC 的历史失败对照见 [四项审计](../../../hil_rl_reproduction.md)。

## 4. Buffer 的存储与采样

`HILReplayBuffer` 继承 SB3 `DictReplayBuffer`，当前只支持 `n_envs=1`。一个物理环形池保存观测、下一观测、最终命令动作、奖励、done 和超时信息；两个布尔数组 `human_mask`、`online_mask` 标记逻辑流归属。

| 来源 | `action_source` | `replay_origin` | 在线流 | 示范流 |
| --- | --- | --- | --- | --- |
| 在线策略 | `policy` | `online`（默认） | 是 | 否 |
| 在线教师/人工接管 | `human` | `online`（默认） | 是 | 是 |
| 导入离线示范 | `human` | `offline_demo` | 否 | 是 |

在线干预只保存一份物理记录，在两个逻辑流中均可采样。默认 `demo_fraction=0.5`，批次 64 时示范流和在线流各抽 32 条；两流内部均为均匀、有放回采样，合并后打乱。在线半批也可能抽到干预；同条经验允许重复，没有优先级采样。若某流为空，整批从另一个流抽取；空池不可采样。

未指定 `--replay-capacity` 时，池容量是 `max(1000, steps + demo_lines + 1)`；指定后使用固定容量。`demo_lines` 为导入文件总行数，实际仅导入 `action_source=human` 的记录。满池时覆盖最旧位置，并同步重写两个标记，防止旧示范身份残留。新经验仍可覆盖离线示范，没有永久示范分区。内存后端结束保存 `replay.pkl`，掩码随池序列化；磁盘后端保存数组与 manifest，支持 API 重开。`sim_train` 当前没有完整续训 CLI。

最近未导入离线示范的实验容量为 1501，实际保存 1500 条；在线流 1500 条，示范流 709 条，离线示范 0 条。逻辑流大小存在交集，不能把 1500 和 709 相加当作物理记录数。完整策略/人工动作审计字段在 JSONL，经验池不保存整份 `info`。字段与超时语义见 [数据格式](../../interfaces/data-formats.md)。

## 录制、产物与验证

`TransitionRecorder` 每步写 JSONL；`validate_recording` 检查形状、有限值、来源与回合连续性。示范导入先校验文件，再核对模型类型和观测空间，只导入 `human` 记录。

输出包括 `policy.zip`、内存后端的 `replay.pkl` 或磁盘后端的 `replay/`、`metrics.json`、`policy_progress.jsonl`、`policy_step_*.zip` 和 `transitions.jsonl`。训练前、默认每 300 步及训练末进行固定种子无接管评估，记录成功率、误差、Actor 参数变化、SAC/BC 更新数和熵系数；可重新加载快照独立评估。

当前本机环境已跑过配置了 A 臂场景的 26 项自动测试。1500 步低熵纯 SAC 的固定 10 回合从 0/10 到 10/10；种子 2000 起的独立 30 回合为 30/30，平均 6.03 步、终点 TCP 误差 0.0167 m；1500 条记录、709 次脚本干预校验通过。环境、参数和产物位置见 [本地环境配置记录](../../simulation/chronicles/2026-10-01-omi-environment.md)。本页机制核查见 [训练实现文档核查](../chronicles/2026-10-01-training-implementation-docs.md)。

## 已知限制

当前只覆盖固定目标、简单初始扰动和单环境仿真；尚无真人连续在线训练、真机 Actor、相机时间同步、自动视觉奖励或分布式通信。JSONL 尚无统一 schema_version、硬件时间戳、设备帧号、策略版本或真实动作确认。源码、CLI 默认值与具体实验配置需分别记录，不能把历史成功参数当成每次启动的默认值。
