# 在线RL历史

从仿真训练和早期HIL接口推进到真机periodic采集、独立Actor/Learner、BC保护与选择性编码器，再到SpacePilot BC6148在线任务。10月17–18的4628等记录只属于旧阶段；10月24日旧任务清理与后续新run需结合项目摘要区分。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/online-rl.md)。

## 阶段记录

- [2026-10-01：训练实现文档核查](records/training/chronicles/2026-10-01-training-implementation-docs.md)
- [2026-10-02：HIL-SERL 参考核查与视觉融合勘误](records/training/chronicles/2026-10-02-hil-serl-reference.md)
- [2026-10-02：USB 资源、Buffer 与总体网络补录](records/training/chronicles/2026-10-02-usb-resources-and-network.md)
- [2026-10-03：Float64MultiArray 动作包与模拟控制端联调](records/training/chronicles/2026-10-03-action-bag.md)
- [2026-10-03：HIL-SERL 人工接管与 ROS 动作接口讨论](records/training/chronicles/2026-10-03-intervention-action-contract.md)
- [2026-10-05：六维真机 HIL、双 Critic 与 Actor/Learner](records/training/chronicles/2026-10-05-hil-actor-learner.md)
- [2026-10-06：真机RL回合采集、异步写盘与首批数据检查](records/training/chronicles/2026-10-06-rl-episode-collection-audit.md)
- [2026-10-07：按回合交替 RL 最小闭环](records/training/chronicles/2026-10-07-alternating-rl.md)
- [2026-10-07：异步 RL 手柄 Back 回 home 与 A/B 夹爪修复](records/training/chronicles/2026-10-07-async-gamepad-home-gripper-fix.md)
- [2026-10-07：异步Actor/Learner及10回合策略刷新](records/training/chronicles/2026-10-07-async-rl.md)
- [2026-10-07：BC保护式RL、模型选择与编码器冻结范围](records/training/chronicles/2026-10-07-bc-protected-rl-and-encoder.md)
- [2026-10-07：人工周期采集现场联调与多回合操作](records/training/chronicles/2026-10-07-human-periodic-collection.md)
- [2026-10-07：新示范、BC 推理与下一步 RL 交接](records/training/chronicles/2026-10-07-new-bc-to-rl-handoff.md)
- [2026-10-07：共享编码器、HIL-SERL 对齐与中断恢复](records/training/chronicles/2026-10-07-shared-serl-resume.md)
- [2026-10-08：新 BC 热启动后的首批真机在线 RL 与 EEF 时序审计](records/training/chronicles/2026-10-08-first-online-rl-run.md)
- [2026-10-09：推理完成后仲裁成为异步 RL 默认](records/training/chronicles/2026-10-09-arbitration-modes.md)
- [2026-10-09：观测驱动动作与时序仅诊断](records/training/chronicles/2026-10-09-observation-driven-control.md)
- [2026-10-09：Start 保留 SAC 十帧输入历史](records/training/chronicles/2026-10-09-start-history-retention.md)
- [2026-10-10：单帧 BC 录制到 Learner 的离线验证](records/training/chronicles/2026-10-10-recorded-bc-learner-validation.md)
- [2026-10-11：batch64在线训练与探索噪声现场核验](records/training/chronicles/2026-10-11-batch64-exploration-live.md)
- [2026-10-11：Critic负Q与稀疏成功监督的离线诊断](records/training/chronicles/2026-10-11-critic-diagnostics.md)
- [2026-10-11：在线策略探索与Actor换权重](records/training/chronicles/2026-10-11-online-exploration.md)
- [2026-10-11：在线HIL RL可运行基线](records/training/chronicles/2026-10-11-runnable-baseline.md)
- [2026-10-11：只继承BC权重，全部训练数据从新会话采集](records/training/chronicles/2026-10-11-weights-only-new-data.md)
- [2026-10-17：SpacePilot采集、两阶段BC与显式参数在线RL](records/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)
- [2026-10-18：SpacePilot在线RL停止后核验与续跑交接](records/training/chronicles/2026-10-18-spacepilot-rl-stopped.md)
- [Training 编年索引](records/training/chronicles/README.md)

## 原机制与领域摘要

- [Training 当前摘要](records/training/current.md)
- [Training 纪传体](records/training/evolution/README.md)
- [六维真机 HIL 环境、SAC 与 Actor/Learner](records/training/evolution/hil-actor-learner.md)
- [HIL-SERL 开源任务与 USB 实现参考](records/training/evolution/hil-serl-reference.md)
- [真机在线 RL：BC 热启动、手柄接管与异步训练](records/training/evolution/real-online-rl.md)
- [SpacePilot 人工采集、BC6148 与显式参数在线 RL](records/training/evolution/spacepilot-bc-online-rl.md)

## 旧教程与导航快照

- [BC12045 预加载与异步 RL 首次试跑](tutorials/bc12045_async_rl_trial.md)

## 其他原文

- [Training 导航](records/training/README.md)
- [Training 架构决定](records/training/decisions/README.md)

- [SpacePilot BC6148 在线 RL：显式 setting 与旧配置对照](snapshots/tutorials--spacepilot_bc6148_online_rl.md)
