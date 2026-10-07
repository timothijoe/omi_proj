# Training 编年索引

- [2026-10-07：人工周期采集现场联调与多回合操作](2026-10-07-human-periodic-collection.md)：Start/RB/成功标签、100 ms 周期审计、有效动作统计、保存期间 Start 排队及现场验证边界。

- [2026-10-07：独立示范/在线双池与固定初始示范](2026-10-07-dual-replay.md)：50/50采样、人工干预双写、固定区保护、离线迁移、跨池恢复边界及GPU验证。

- [2026-10-07：BC保护式RL、模型选择与编码器冻结范围](2026-10-07-bc-protected-rl-and-encoder.md)：periodic有效段入池、BC初始化完整SAC、Critic预热与BC约束；旧295与新11795选择标准、视觉/触觉/历史帧训练范围及权重实测。

- [2026-10-07：周期控制、成功动作回放与BC拟合诊断](2026-10-07-periodic-replay-bc-fitting.md)：periodic审计边界、BC label与policy同动作链路、单回合3295及全8回合11795模型、训练证据与待办。

- [2026-10-07：异步 RL 手柄 Back 回 home 与 A/B 夹爪修复](2026-10-07-async-gamepad-home-gripper-fix.md)：入口遗漏、路由参数与夹爪依赖的修复；67项软件测试，真机待确认。

- [2026-10-07：异步Actor/Learner及10回合策略刷新](2026-10-07-async-rl.md)：当前主入口、一键启动范围、Ctrl+C关闭边界、106项测试与GPU并发证据、未完成项。

- [2026-10-07：按回合交替RL最小闭环](2026-10-07-alternating-rl.md)：此前串行闭环与短按修复；后续主入口改为异步。

- [2026-10-07：共享编码器、HIL-SERL对齐与中断恢复](2026-10-07-shared-serl-resume.md)：v2网络、续训及多源离线数据。

- [2026-10-06：RL回合采集、异步写盘与首批数据检查](2026-10-06-rl-episode-collection-audit.md)：最新按键/自动保留、1723条只读审计、未修复短按漏检和待核实成功标签。

- [2026-10-05：本窗口开发记录覆盖核查](2026-10-05-session-documentation-audit.md)：功能与文档对应、阶段状态修订、显示尺度和后继EEF说明。

- [2026-10-05：现场后退诊断、推理录制与无wrench对照](2026-10-05-policy-input-audit-no-wrench.md)：三轮训练、仲裁时序、手动话题、RGB时效、225窗口重放与未解决问题。

- [2026-10-05：四个真实日期包转换与wrench BC训练](2026-10-05-passive-bc-wrench.md)：1005条样本、整包验证划分、wrench网络分支与CUDA训练。

- [2026-10-05：独立手柄四包检查与真实指令可视化](2026-10-05-passive-demo-audit.md)：335条预览、wrench、时效检查、左右键操作及待标注事项。

- [2026-10-05：独立示范采集与命令监督 BC](2026-10-05-demo-collection-bc.md)

- [2026-10-05：六维真机HIL环境、双Critic与Actor/Learner](2026-10-05-hil-actor-learner.md)

- [2026-10-05：完整 transition 磁盘导入与在线分流 API](2026-10-05-transition-replay.md)

- [2026-10-04：实时policy、RB仲裁与SDK转换接通](2026-10-04-policy-gamepad-integration.md)

- [2026-10-04：无关节模型实时影子入口与现场EEF阻塞](2026-10-04-stack-live-shadow.md)

- [2026-10-04：无关节反馈版本GPU训练](2026-10-04-nojoint-gpu-training.md)


- [2026-10-04：独立CUDA环境与策略推理时延对照](2026-10-04-cuda-policy-latency.md)

- [2026-10-04：六关键点本地候选与人工审核](2026-10-04-six-keypoint-review.md)：实现、验收、交付反馈与独立纪传体归档。

- [2026-10-04：当前帧独立＋过去9帧拼接，完成2000步对照](2026-10-04-current-stack-history.md)

- [2026-10-04：下载ResNet-10并完成2000步历史策略训练](2026-10-04-resnet10-history.md)

- [2026-10-04：暂定基坐标系旋转向量与转换说明](2026-10-04-axis-rotation-assumption.md)

- [2026-10-04：核对 axis_test 实机接口与单位差异](2026-10-04-axis-controller-interface.md)

- [2026-10-04：在线历史推理与 wrench 有效性标签](2026-10-04-history-online-wrench.md)

- [2026-10-03：bag_002移入训练、替换验证包并重训对照](2026-10-03-validation-resplit.md)

- [2026-10-03：最近1秒历史GRU训练与单帧对照](2026-10-03-history-gru-training.md)

- [2026-10-03：完成tactile和bc迁移，保留eef_bc](2026-10-03-tactile-bc-archive-complete.md)

- [2026-10-03：正式录包首轮2000步训练，验证未优于基线](2026-10-03-formal-training-run1.md)

- [2026-10-03：历史实验数据外置归档，因并行写入暂停迁移](2026-10-03-experiment-data-archive.md)

- [2026-10-03：正式10包审计与离线v3转换，训练待确认](2026-10-03-formal-dataset.md)

- [2026-10-03：Float64MultiArray动作包与模拟控制端联调](2026-10-03-action-bag.md)

编年记录保存已验证阶段，后续修订以新记录或勘误追加。

- [2026-10-01：仿真接管、示范导入与 SAC 训练](2026-10-01-hil-sim-training.md)
- [2026-10-01：HIL 双流与策略改善审计](2026-10-01-policy-improvement-audit.md)
- [2026-10-01：低熵纯 SAC 策略改善](2026-10-01-low-entropy-sac.md)
- [2026-10-01：训练实现文档核查](2026-10-01-training-implementation-docs.md)
- [2026-10-02：HIL-SERL 参考核查与视觉融合勘误](2026-10-02-hil-serl-reference.md)
- [2026-10-02：磁盘 HIL 经验池与后台预取](2026-10-02-disk-replay.md)
- [2026-10-02：USB 资源、Buffer 与总体网络补录](2026-10-02-usb-resources-and-network.md)
- [2026-10-03：真实录包BC训练与ROS影子推理](2026-10-03-bag-bc-shadow.md)
- [2026-10-03：HIL-SERL 接管与 ROS 动作接口讨论](2026-10-03-intervention-action-contract.md)

- [2026-10-03：bag_004末端动作空间第一版](2026-10-03-eef-action-space.md)

- [2026-10-03：腕部策略输入与相机可用性标记](2026-10-03-wrist-policy-input.md)
