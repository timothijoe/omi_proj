# 仿真 HIL RL 四项复现审计

本页回答“训练、动作干预、buffer、policy improvement 是否真的实现”。范围仅限 MuJoCo A 臂任务；与真实设备控制无关。参考原版 `hil-serl/examples/train_rlpd.py` 的 actor→双 buffer→混合采样→SAC 更新路径，OMI 使用单进程 SB3 实现相同数据语义。**不是对原版 JAX/AgentLace 或 LeRobot 分布式代码的逐行移植。**

| 项目 | OMI 当前实现 | 可检查证据 | 尚未复现的部分 |
| --- | --- | --- | --- |
| 1. RL 完整训练流程 | 环境交互、脚本示范/接管、SAC critic/actor/温度更新、检查点、固定种子无接管评估 | `training.sim_train` 保存 `policy_progress.jsonl`、`policy_step_*.zip`、`policy.zip`、`replay.pkl`；A 臂 1500 步运行 | 分布式 actor/learner、图像奖励、真实设备 |
| 2. 干预动作实施 | 策略提议后由教师或键盘覆盖，同一路径裁剪并下发到 MuJoCo；原始动作与最终命令均记录 | `sim.interactive_rollout` 两步回归中 1 条人工覆盖、1 条策略动作；录制校验通过 | 连续低延迟真人接管与硬件反馈确认 |
| 3. Buffer | 在线流收全部在线 transition；示范流收人工/脚本干预及离线示范；批次按配置从两流取样 | 单元测试验证离线示范不进入在线半批、在线干预进入两流、环形覆盖清理旧标记；训练输出 `replay_streams` | 独立进程/服务缓冲，原版大规模数据集机制 |
| 4. Policy improvement | SB3 SAC 更新 actor/critic/温度，另可选示范 BC；固定种子基线、周期评估、参数变化和更新次数可追踪 | `bc_weight=0`、初始熵系数 `0.01` 时，1500 步由 0/10 到 10/10；另取 30 回合为 30/30 | 原版 JAX/LeRobot 分布式训练未复刻；超参数变化对结果影响明显 |

## 关键数据语义

环境报告 `policy_action`、`human_action`、`executed_action` 和 `action_source`。回放存储的是限位后的 `executed_action`。这里“executed”指**仿真下发的命令增量**；并非真实机器人反馈位移。在线干预同时进入在线流与示范流；从键盘 JSONL 导入的离线示范只进入示范流。这样采样时离线示范不会污染在线半批。默认 `demo_fraction=0.5`，即有两流数据时一半从示范流、一半从在线流；在线干预可在两流出现，符合原版 actor 将干预 transition 同时插入两类 store 的语义。

## Policy improvement 的解释

标准 SAC 的策略更新在 SB3 中执行：critic 学习带目标网络的 Bellman 值，actor 最小化由熵项与 `min(Q1,Q2)` 构成的目标，温度系数按目标熵更新。OMI 的 `DemoRegularizedSAC` 在 SAC 更新后可选地追加接管样本的行为克隆 MSE 更新。固定种子评估没有干预，避免用教师完成的回合伪装成策略成功。

| 设置 | 训练步 | SAC/BC 更新 | 固定 10 回合 | 另取 30 回合 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| 初始熵 1.0、BC 权重 10 | 1500 | 1400/1400 | 10/10 | 30/30 | 组合方法成功 |
| 初始熵 1.0、BC 权重 0 | 1500 | 1400/0 | 0/10 | 未测 | 默认熵设置下失败 |
| 初始熵 1.0、BC 权重 0 | 5000 | 4900/0 | 0/10 | 未测 | 单纯延长步数未解决 |
| 初始熵 0.01、BC 权重 0 | 1500 | 1400/0 | 10/10 | 30/30 | **纯 SAC + 示范双流取得策略改善** |

低熵纯 SAC 的固定种子策略由 0/10 到 10/10，平均终点 TCP 误差从 0.447 m 降至 0.022 m，平均完成 6.3 步。初始/最终快照重新加载复验一致；[纯 SAC 学习曲线](evidence/a_reach_sac_policy_improvement.png)显示到后期才越过成功阈值。组合设置的[学习曲线](evidence/a_reach_policy_improvement.png)也保留作对照。两个成功设置都只证明此简单仿真任务中的策略改善。

这些对照说明“actor 参数改变”本身不够，必须看无干预表现；初始熵系数在七维动作任务上显著影响结果。纯 SAC 成功设置仍使用脚本示范和接管的双流数据，不是无示范的普通 SAC。实验仅使用固定目标、简单初始扰动，不能据此声称跨目标泛化，也不等于逐行复刻参考项目的 JAX/AgentLace 或 LeRobot 分布式实现。

## 操作入口

参见 [A 臂训练教程](../tutorials/a_arm_simulation.md)、[交互接管教程](../tutorials/interactive_intervention.md) 和 [录制教程](../tutorials/recording_and_replay.md)。模型资源仍需由 `--scene` 指定。当前真机部分暂停。
