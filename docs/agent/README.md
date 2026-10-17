# Agent 知识库

SpacePilot 输入与本地物体操控见 [hardware 当前能力](hardware/evolution/spacepilot-pose.md)。另有[机械臂增量发送入口](hardware/evolution/spacepilot-control.md)，已实现软件接口，真机待验收，尚未接入训练控制链。

2026-10-12训练入口：[当前训练说明与文档汇总](../current_training_guide.md)
· [常用启动/续跑命令](../../tutorials/common_live_commands.md#rl-new)
· [全部Markdown索引](../markdown_index.md)。Oct 11在线采集/训练/权重交接已有真实运行与归档证据。

推荐顺序：先读 [能力总表](../capabilities.md)，再读目标领域 `current.md` → 对应 `evolution/` → 接口文档；需要理解形成过程时读 `chronicles/`，改变长期边界前读 `decisions/`。

| 领域 | 当前状态 | 详细能力 |
| --- | --- | --- |
| [simulation](simulation/README.md) | [A 臂 MJCF 任务](simulation/current.md) | [模型与任务](simulation/evolution/model-and-task.md) |
| [training](training/README.md) | [接管、录制与 SAC](training/current.md) | [训练数据链](training/evolution/hil-training.md) |
| [hardware](hardware/README.md) | [接收端与传感器现场状态](hardware/current.md) | [Tianji 适配器](hardware/evolution/tianji-adapter.md) |

[接口索引](interfaces/README.md)横跨三个领域。维护时以纪传体记最新事实，以编年体记发生过且已验证的阶段；章程只记稳定原则。
能力与待办以各领域current和最新日期的验收证据为准；早期“未接设备/实机RL暂缓”的描述不再代表当前训练基线。
参考项目及旧文档只能作为线索，不能替代当前代码验收。
