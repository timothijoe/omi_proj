# Agent 知识库

推荐顺序：先读 [能力总表](../capabilities.md)，再读目标领域 `current.md` → 对应 `evolution/` → 接口文档；需要理解形成过程时读 `chronicles/`，改变长期边界前读 `decisions/`。

| 领域 | 当前状态 | 详细能力 |
| --- | --- | --- |
| [simulation](simulation/README.md) | [A 臂 MJCF 任务](simulation/current.md) | [模型与任务](simulation/evolution/model-and-task.md) |
| [training](training/README.md) | [接管、录制与 SAC](training/current.md) | [训练数据链](training/evolution/hil-training.md) |
| [hardware](hardware/README.md) | [SDK 适配，未接设备](hardware/current.md) | [Tianji 适配器](hardware/evolution/tianji-adapter.md) |

[接口索引](interfaces/README.md)横跨三个领域。维护时以纪传体记最新事实，以编年体记发生过且已验证的阶段；章程只记稳定原则。暂缓范围：真实控制器连接与运动、相机时间同步、图像奖励、LeRobot 分布式 actor/learner、实机在线 RL。参考项目及旧文档只能作为线索，不能替代当前代码验收。
