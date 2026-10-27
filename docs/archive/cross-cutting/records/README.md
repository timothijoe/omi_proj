> 历史资料：原路径 `docs/agent/README.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../current.md)；本页保留原过程与证据。

# Agent 知识库

SpacePilot已从[本地物体操控](../../teleoperation/records/hardware/evolution/spacepilot-pose.md)、[独立增量发送](../../teleoperation/records/hardware/evolution/spacepilot-control.md)接入[人工采集与在线HIL](../../teleoperation/records/hardware/evolution/spacepilot-hil.md)。2026-10-17新采数据已训练BC6148并由用户启动在线RL；最新完整现状见[训练纪传](../../online-rl/records/training/evolution/spacepilot-bc-online-rl.md)，过程见[当天编年](../../online-rl/records/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)。

2026-10-12训练入口：[当前训练说明与文档汇总](../../../current_training_guide.md)
· [常用启动/续跑命令](../../../../tutorials/common_live_commands.md#rl-new)
· [全部Markdown索引](../../../markdown_index.md)。Oct 11在线采集/训练/权重交接已有真实运行与归档证据。

推荐顺序：先读 [能力总表](../../../capabilities.md)，再读目标领域 `current.md` → 对应 `evolution/` → 接口文档；需要理解形成过程时读 `chronicles/`，改变长期边界前读 `decisions/`。

| 领域 | 当前状态 | 详细能力 |
| --- | --- | --- |
| [simulation](../../simulation/records/simulation/README.md) | [A 臂 MJCF 任务](../../simulation/records/simulation/current.md) | [模型与任务](../../simulation/records/simulation/evolution/model-and-task.md) |
| [training](../../online-rl/records/training/README.md) | [接管、录制与 SAC](../../online-rl/records/training/current.md) | [训练数据链](../../simulation/records/training/evolution/hil-training.md) |
| [hardware](hardware/README.md) | [接收端与传感器现场状态](hardware/current.md) | [Tianji 适配器](../../control/records/hardware/evolution/tianji-adapter.md) |

[接口索引](interfaces/README.md)横跨三个领域。维护时以纪传体记最新事实，以编年体记发生过且已验证的阶段；章程只记稳定原则。
能力与待办以各领域current和最新日期的验收证据为准；早期“未接设备/实机RL暂缓”的描述不再代表当前训练基线。
参考项目及旧文档只能作为线索，不能替代当前代码验收。
