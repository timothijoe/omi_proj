# 当前训练阅读与操作入口

当前实现见[在线RL模块](modules/online-rl.md)，实际操作见[SpacePilot BC6148教程](../tutorials/spacepilot_bc6148_online_rl.md)。

| 问题 | 说明 |
| --- | --- |
| 选定配置、最近run和未完成问题 | [项目摘要](current.md) |
| 从BC建新任务／已有任务续跑 | [基线操作](../tutorials/spacepilot_bc6148_online_rl.md)；已有run不要再次prepare |
| 数据、缓存与恢复 | [经验池模块](modules/replay.md)、[缓存教程](../tutorials/cached_replay.md) |
| 查看Actor/Learner与回合 | [训练监控](../tutorials/training_monitor.md) |
| 外部相机旧图问题 | [传感器](modules/sensors.md)、[门控与监控待办](design/system-health-monitoring.md) |

主JSON默认路径与10月24日最后观察到的新任务不同；续跑须核对显式`--run`。
旧45秒／BC12045参数和当时库存不作为新任务默认。
旧汇总全文见[历史快照](archive/cross-cutting/snapshots/docs--current_training_guide.md)。
