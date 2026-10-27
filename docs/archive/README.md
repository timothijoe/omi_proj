# 模块历史归档

这里不是默认阅读路线。先看[当前摘要](../current.md)和对应模块，只有追溯实验／设计原因时才进入原文。
归档使用本仓库迁移前的最新原文，不用ztt的旧记录覆盖；日期、命令、失败和验证边界保留。

| 模块 | 历史主题 |
| --- | --- |
| [在线RL](online-rl/README.md) | 从仿真训练和早期HIL接口推进到真机periodic采集、独立Actor/Learner、BC保护与选择性编码器，再到SpacePilot BC6148在线任务 |
| [示范与BC](bc/README.md) | 早期录包使用关节目标或未来EEF变化代理标签，随后转向已接受命令标签的人工回合采集 |
| [经验池与存储](replay/README.md) | 记录磁盘后端、共享双池、单帧存储、数据搬迁和完整恢复演变 |
| [策略模型](policy/README.md) | 保留旧关节／EEF代理模型、ResNet历史、无关节和current9stack对照 |
| [机器人控制](control/README.md) | 从SDK边界和动作接口推进到ROS接收端、速度保持、触觉保护及真实响应排查 |
| [人工输入](teleoperation/README.md) | 从手柄／虚拟物体操控到SpacePilot独立控制，再接入人工采集与在线HIL |
| [传感器](sensors/README.md) | 保留原始图、数值场、设备侧身份、基线、腕部ROI／共享内存／解耦和时钟诊断过程 |
| [AprilTag](marker/README.md) | 保留原件迁入、多姿态X/Z标定、默认相对关系和跟随演变 |
| [仿真](simulation/README.md) | 保留外部A臂MJCF、到达任务、奖励、示范与SAC验证 |
| [监控与可视化](visualization/README.md) | 从离线录包／旧实时整图看板演变到训练网页与独立RViz V2 |
| [跨模块与工作快照](cross-cutting/README.md) | 保留旧首页、能力表、跨领域设计和开发快照，作为当时背景与决策证据 |

迁移盘点与保留校验在[_migration](_migration/README.md)，不属于入门背景。原始证据继续保留在`docs/evidence/`及登记的local／外盘位置。
