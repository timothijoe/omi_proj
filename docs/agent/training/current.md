# Training 当前摘要

已补充[原版 HIL-SERL 接管与经验记录](evolution/hil-serl-reference.md#人工接管动作记录与训练采样)，
并记录[ROS 类型化动作与统一选择方向](../../design/bag-bc-shadow-policy.md#人工接管与类型化动作接口待实现)。
当前影子预测仍为 String JSON；类型化消息及 ROS 人工接管链路尚未实现。

新增[录包BC与ROS影子推理](evolution/bag-bc-shadow.md)：真实导出108个样本，500步CPU训练，
同段RMSE降至0.001781 rad；两轮ROS回放218次预测且输入精确一致。
这是单段过拟合/消息链路验证，无独立成功示教验证，不证明插孔能力。
动作绝对弧度语义待确认，只输出shadow预测，不使用腕部/夹爪/TCP。
入口 `scripts/bag_bc.sh`，见[教程](../../../tutorials/bag_bc_shadow.md)。

已增加 [磁盘经验池](evolution/disk-replay.md)，使用 memmap、后台 batch 预取、双流 ring 和干净检查点恢复，训练通过 `--replay-backend disk` 选择。40 项自动测试通过；A 臂 200 步完成 SAC/BC 更新与容量覆盖，短跑不证明策略收敛。图像字段通过合成数据验证，视觉任务、超内存冷盘性能及真机尚未验证。

原版任务及 USB 的动作、奖励/超时、SpaceMouse、观测 shape、RTX 4090、Buffer 与视觉网络核查见 [HIL-SERL 参考](evolution/hil-serl-reference.md)。USB 环境和视觉策略尚未接入 OMI。原版两个池填满的图像数组约 98.3 GB，是源码估算；在线网络约 9.38M、奖励分类器约 6.09M，骨干冻结、投影和控制头可训练，融合特征 832 维。最新补录见 [USB 资源与网络记录](chronicles/2026-10-02-usb-resources-and-network.md)，原始融合维度勘误见 [首次记录](chronicles/2026-10-02-hil-serl-reference.md)。

目前使用单进程 SB3 SAC、可选示范 BC、在线/示范双流回放和 JSONL 录制。训练中的干预来自脚本教师，覆盖整步七维动作后经过共同限位入口；真人键盘覆盖用于已有策略的逐步运行与录制，尚未接入在线训练。训练奖励为 TCP 距离进度、每步惩罚和成功奖励；独立评估使用稀疏奖励。经验池保存最终命令动作，默认每批在线/示范各半。

最新机制、参数和限制见 [HIL 训练纪传体](evolution/hil-training.md)。本机环境最近的 1500 步低熵纯 SAC 复验完成 1400 次 SAC 更新、0 次 BC 更新，固定评估 0/10 → 10/10，独立 30 回合为 30/30；仍使用脚本示范和接管。26 项测试已在配置本地 A 臂场景的环境通过。历史默认熵纯 SAC 失败对照见 [四项审计](../../hil_rl_reproduction.md)。真人连续干预、真机反馈与 LeRobot 分布式 actor/learner 尚未接入。

形成过程见 [首期编年](chronicles/2026-10-01-hil-sim-training.md)、[双流审计](chronicles/2026-10-01-policy-improvement-audit.md)、[低熵实验](chronicles/2026-10-01-low-entropy-sac.md)、[本地环境复验](../simulation/chronicles/2026-10-01-omi-environment.md)和[实现文档核查](chronicles/2026-10-01-training-implementation-docs.md)。
