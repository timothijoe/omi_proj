> 历史资料：原路径 `docs/agent/training/evolution/README.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/online-rl.md)；本页保留原过程与证据。

# Training 纪传体

- [SpacePilot采集、BC6148与显式参数在线RL](spacepilot-bc-online-rl.md)：新示范选择、两阶段CUDA拟合、动作契约、触觉解冻、旧参数回归、恢复和现场证据。

功能级事实已于2026-10-12同步当前可运行版本；具体操作见[常用指令](../../../../../../tutorials/common_live_commands.md)，
时间证据见[编年索引](../chronicles/README.md)。

- [共享内存缓存双池](../../../../replay/records/training/evolution/cached-replay.md)：Demo/RL独立抽样、共享物理数据、全量磁盘索引、受管字节预算、后台加载与预取。

- [Actor/Learner 统一训练监控](../../../../visualization/records/training/evolution/training-monitor.md)：后台心跳、仲裁、传感器、数据链、权重版本和只读回合审阅。

- [真机在线 RL：BC 热启动、手柄接管与异步训练](real-online-rl.md)：weights-only新建空池、自动续跑、45秒/batch64、冻结与gamma、受限探索、权重交接、归档恢复及旧后端兼容。

- [手柄示范录包、动作语义与 BC 数据入口](../../../../bc/records/training/evolution/demo-collection-bc.md)：当前独立gamepad、集成collector和诊断数据的区别；触觉历史、wrench及可视化。

- [六维真机HIL、SAC和Actor/Learner](hil-actor-learner.md)：当前进展、按钮回合、整段审核、验证边界与下一阶段；[操作教程](../../../../../../tutorials/hil_actor_learner.md)。

- [完整transition磁盘入口](../../../../../../tutorials/transition_replay.md)：旧磁盘后端的目录、分流与恢复；当前真机Learner与cached双池已接入，见上方专题。

- [禁用关节输入的GPU历史拼接训练](../../../../policy/records/training/evolution/nojoint-stack.md)


- [六关键点自动预标注与人工审核工具](../../../../visualization/records/training/evolution/six-keypoint-review.md)：独立专题，维护点定义、算法、界面与标注契约。

- [当前帧独立＋历史通道拼接，无GRU对照](../../../../policy/records/training/evolution/current-stack-history.md)

- [冻结ResNet-10与历史GRU对照](../../../../policy/records/training/evolution/resnet10-history.md)

- [对齐 axis_test 实机动作接口](../../../../control/records/training/evolution/axis-controller-interface.md)

- [在线历史 policy 与可选 wrench](../../../../policy/records/training/evolution/history-online-policy.md)

- [oct_03 当前实验与设计总结](../../../../cross-cutting/records/training/evolution/oct_03-experiment-design-summary.md)

- [oct_03 训练日志：单帧与历史GRU对照](../../../../cross-cutting/records/training/evolution/oct_03-training-log.md)

功能级最新事实在此维护；历史见 [编年索引](../chronicles/README.md)。

- [HIL 训练与数据流](../../../../simulation/records/training/evolution/hil-training.md)
- [录包BC与ROS影子推理](../../../../bc/records/training/evolution/bag-bc-shadow.md)
- [磁盘经验池、预取与恢复](../../../../replay/records/training/evolution/disk-replay.md)
- [HIL-SERL 开源任务、USB、SpaceMouse 与视觉参考](hil-serl-reference.md)

- [左臂末端增量、代理标签与类型化影子候选](../../../../policy/records/training/evolution/eef-action-space.md)
