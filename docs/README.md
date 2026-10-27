# OMI 文档入口

初次了解项目，先读本页和[当前摘要](current.md)。理解具体功能时选一个模块；执行操作时查[教程](../tutorials/README.md)。
当前结构整理于2026-10-26，内容以本仓库实现及最新适用证据为准；运行快照始终保留采样日期。

| 模块 | 查什么 |
| --- | --- |
| [在线RL](modules/online-rl.md) | Actor/Learner、仲裁、奖励、更新、初始化与续跑 |
| [示范与BC](modules/bc.md) | 人工数据、标签、BC6148来源与验证边界 |
| [经验池与存储](modules/replay.md) | 帧库、共享双池、清理台账与完整恢复 |
| [策略模型](modules/policy.md) | 十帧输入、编码器、六维动作契约 |
| [机器人控制](modules/control.md) | 接收端、坐标／单位、SDK提交与停止边界 |
| [人工输入](modules/teleoperation.md) | SpacePilot／手柄、按键、接管与调度 |
| [传感器](modules/sensors.md) | 相机／触觉来源、数值字段、时间与新鲜度 |
| [AprilTag](modules/marker.md) | 标定、关系保存、跟随及当前关闭状态 |
| [仿真](modules/simulation.md) | 七关节到达、模型资源与评估范围 |
| [监控与可视化](modules/visualization.md) | RViz V2、三列bar、训练网页与历史回放 |

常用操作：[V2实时看板](../tutorials/grid_live_review_v2.md) · [SpacePilot在线训练](../tutorials/spacepilot_bc6148_online_rl.md) · [训练网页](../tutorials/training_monitor.md)。

按需查阅：[共享接口](interfaces/README.md) · [长期原则](decisions/README.md) · [设计与待办](design/README.md)
· [术语](../CONTEXT.md) · [副作用边界](safety.md)。

**历史原文在[模块归档](archive/README.md)，不是默认阅读材料。** 其中的“当前”“运行中”和命令只适用于原时期。
普通检索可用`rg -n --glob '*.md' --glob '!**/archive/**' '关键词' docs tutorials`。
迁移规则、原文去向和检查结果见[文档重构记录](design/documentation-reorganization.md)。
