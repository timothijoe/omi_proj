# Training 纪传体

功能级事实已于2026-10-12同步当前可运行版本；具体操作见[常用指令](../../../../tutorials/common_live_commands.md)，
时间证据见[编年索引](../chronicles/README.md)。

- [共享内存缓存双池](cached-replay.md)：Demo/RL独立抽样、共享物理数据、全量磁盘索引、受管字节预算、后台加载与预取。

- [Actor/Learner 统一训练监控](training-monitor.md)：后台心跳、仲裁、传感器、数据链、权重版本和只读回合审阅。

- [真机在线 RL：BC 热启动、手柄接管与异步训练](real-online-rl.md)：weights-only新建空池、自动续跑、45秒/batch64、冻结与gamma、受限探索、权重交接、归档恢复及旧后端兼容。

- [手柄示范录包、动作语义与 BC 数据入口](demo-collection-bc.md)：当前独立gamepad、集成collector和诊断数据的区别；触觉历史、wrench及可视化。

- [六维真机HIL、SAC和Actor/Learner](hil-actor-learner.md)：当前进展、按钮回合、整段审核、验证边界与下一阶段；[操作教程](../../../../tutorials/hil_actor_learner.md)。

- [完整transition磁盘入口](../../../../tutorials/transition_replay.md)：旧磁盘后端的目录、分流与恢复；当前真机Learner与cached双池已接入，见上方专题。

- [禁用关节输入的GPU历史拼接训练](nojoint-stack.md)


- [六关键点自动预标注与人工审核工具](six-keypoint-review.md)：独立专题，维护点定义、算法、界面与标注契约。

- [当前帧独立＋历史通道拼接，无GRU对照](current-stack-history.md)

- [冻结ResNet-10与历史GRU对照](resnet10-history.md)

- [对齐 axis_test 实机动作接口](axis-controller-interface.md)

- [在线历史 policy 与可选 wrench](history-online-policy.md)

- [oct_03 当前实验与设计总结](oct_03-experiment-design-summary.md)

- [oct_03 训练日志：单帧与历史GRU对照](oct_03-training-log.md)

功能级最新事实在此维护；历史见 [编年索引](../chronicles/README.md)。

- [HIL 训练与数据流](hil-training.md)
- [录包BC与ROS影子推理](bag-bc-shadow.md)
- [磁盘经验池、预取与恢复](disk-replay.md)
- [HIL-SERL 开源任务、USB、SpaceMouse 与视觉参考](hil-serl-reference.md)

- [左臂末端增量、代理标签与类型化影子候选](eef-action-space.md)
