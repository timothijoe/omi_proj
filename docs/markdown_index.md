# 项目Markdown全量索引

整理日期：2026-10-12，共 **283份** Markdown。
范围为本项目Git已跟踪及未忽略的Markdown；不扫描local实验输出、虚拟环境、外盘包或被忽略的第三方依赖。
这是全量路径/标题导航；当前训练的内容总结见[当前训练说明](current_training_guide.md)，可复制命令见[常用指令](../tutorials/common_live_commands.md)。
日期编年保留当时事实，旧命令和状态不自动代表当前默认。

重新核对清单可使用 `git ls-files --cached --others --exclude-standard -- '*.md'`（去重后按实际文件计数）。

## 文档总览与跨领域说明（11）

| 文件 | 标题 |
| --- | --- |
| [docs/README.md](README.md) | OMI 文档总目录 |
| [docs/a_arm_reach.md](a_arm_reach.md) | A 臂 MuJoCo 首期任务与验证 |
| [docs/agent/README.md](agent/README.md) | Agent 知识库 |
| [docs/capabilities.md](capabilities.md) | 能力总表 |
| [docs/current_training_guide.md](current_training_guide.md) | 当前训练说明与文档汇总 |
| [docs/hil_rl_reproduction.md](hil_rl_reproduction.md) | 仿真 HIL RL 四项复现审计 |
| [docs/markdown_index.md](markdown_index.md) | 项目Markdown全量索引 |
| [docs/marker_detect.md](marker_detect.md) | AprilTag marker 相机位姿与手眼标定 |
| [docs/quickstart.md](quickstart.md) | 开发最短入口 |
| [docs/safety.md](safety.md) | 安全与副作用边界 |
| [docs/tianji_hil_rl.md](tianji_hil_rl.md) | 天机机械臂 HIL RL：早期控制接口调查 |

## 操作教程（69）

| 文件 | 标题 |
| --- | --- |
| [tutorials/README.md](../tutorials/README.md) | 操作教程 |
| [tutorials/a_arm_simulation.md](../tutorials/a_arm_simulation.md) | A 臂任务、训练与独立评估 |
| [tutorials/alternating_rl.md](../tutorials/alternating_rl.md) | 按回合交替的真机 RL（2026-10-07 最小版本） |
| [tutorials/async_rl.md](../tutorials/async_rl.md) | 异步真机 RL：每 10 个完整回合检查新策略 |
| [tutorials/bag_bc_shadow.md](../tutorials/bag_bc_shadow.md) | 录包 → BC初始策略 → ROS影子推理 |
| [tutorials/bc12045_async_rl_trial.md](../tutorials/bc12045_async_rl_trial.md) | BC12045 预加载与异步 RL 首次试跑 |
| [tutorials/bc_replay_testing.md](../tutorials/bc_replay_testing.md) | BC模型测试与成功动作label回放 |
| [tutorials/cached_replay.md](../tutorials/cached_replay.md) | 双池内存缓存：全量数据留盘，后台加载训练 |
| [tutorials/circle_test.md](../tutorials/circle_test.md) | 右臂六维增量画圆 |
| [tutorials/common_live_commands.md](../tutorials/common_live_commands.md) | 真机常用启动指令汇总 |
| [tutorials/corrected_stand_review.md](../tutorials/corrected_stand_review.md) | Stand 关节方向修正版（只读可视化） |
| [tutorials/current_stack_history.md](../tutorials/current_stack_history.md) | 当前帧独立＋过去9帧通道拼接 |
| [tutorials/daimon_live.md](../tutorials/daimon_live.md) | 戴蒙双指触觉与腕部相机实时预览 |
| [tutorials/demo_bag_dataset.md](../tutorials/demo_bag_dataset.md) | 独立手柄录包、数据检查与逐帧可视化 |
| [tutorials/demo_collection_bc.md](../tutorials/demo_collection_bc.md) | 集成手柄 Demo 采集、指令标签与 BC |
| [tutorials/disk_replay.md](../tutorials/disk_replay.md) | 使用磁盘经验池 |
| [tutorials/eef_action_bag.md](../tutorials/eef_action_bag.md) | 末端动作 rosbag 与模拟控制端联调 |
| [tutorials/eef_action_space.md](../tutorials/eef_action_space.md) | bag_004：末端动作空间、BC与影子推理 |
| [tutorials/eef_history_online.md](../tutorials/eef_history_online.md) | 历史 policy 在线推理与 wrench 开关 |
| [tutorials/eef_pose_replay.md](../tutorials/eef_pose_replay.md) | 将录制的末端位姿转为增量并回放 |
| [tutorials/environment_setup.md](../tutorials/environment_setup.md) | 仿真环境安装与激活 |
| [tutorials/gamepad_control.md](../tutorials/gamepad_control.md) | 手柄控制、SDK 换轴与 RB 接管 |
| [tutorials/gamepad_reproduce_on_other_pc.md](../tutorials/gamepad_reproduce_on_other_pc.md) | 在其他电脑复现手柄末端控制：Agent 执行手册 |
| [tutorials/grid_bag_review.md](../tutorials/grid_bag_review.md) | 小矩阵触觉＋腕部ROI＋机器人：通用RViz回放 |
| [tutorials/grid_live_review.md](../tutorials/grid_live_review.md) | 实时相机、触觉与末端位姿 RViz 看板 |
| [tutorials/hardware_preflight.md](../tutorials/hardware_preflight.md) | 真机准备：只读阶段 |
| [tutorials/hil_actor_learner.md](../tutorials/hil_actor_learner.md) | 六维真机 HIL 环境、SAC 与 Actor/Learner |
| [tutorials/hybrid_urdf_review.md](../tutorials/hybrid_urdf_review.md) | 新外观与旧运动链对照 |
| [tutorials/interactive_intervention.md](../tutorials/interactive_intervention.md) | 策略运行中的键盘干预 |
| [tutorials/keyboard_demonstration.md](../tutorials/keyboard_demonstration.md) | 键盘录制 A 臂示范 |
| [tutorials/local_data_storage.md](../tutorials/local_data_storage.md) | 本机 local 与外接盘数据的使用 |
| [tutorials/machine_transfer_checklist.md](../tutorials/machine_transfer_checklist.md) | 换机器：额外拷贝与重新安装清单 |
| [tutorials/marker_detect.md](../tutorials/marker_detect.md) | RealSense AprilTag marker 检测与位姿记录 |
| [tutorials/marvin_messages.md](../tutorials/marvin_messages.md) | 项目本地 marvin_msgs 消息包 |
| [tutorials/no_wrench_policy_record.md](../tutorials/no_wrench_policy_record.md) | 当前操作：无六维力/力矩模型推理与观测录制 |
| [tutorials/nojoint_stack_training.md](../tutorials/nojoint_stack_training.md) | 不使用关节反馈的历史拼接策略：GPU训练 |
| [tutorials/oct11_archive_restore.md](../tutorials/oct11_archive_restore.md) | Oct 11在线RL归档、恢复与buffer重建 |
| [tutorials/oct3_formal_dataset.md](../tutorials/oct3_formal_dataset.md) | oct3正式录包：检查、转换与训练 |
| [tutorials/passive_bag_bc_wrench.md](../tutorials/passive_bag_bc_wrench.md) | 日期 bag → 含双指六维力/力矩的 BC 训练 |
| [tutorials/policy_gamepad.md](../tutorials/policy_gamepad.md) | 实时 policy、RB 接管与 SDK 输出 |
| [tutorials/quickstart.md](../tutorials/quickstart.md) | 最短可运行仿真案例 |
| [tutorials/recording_and_replay.md](../tutorials/recording_and_replay.md) | 录制、示范导入与可视化 |
| [tutorials/resnet10_history.md](../tutorials/resnet10_history.md) | 冻结ResNet-10历史策略实验 |
| [tutorials/rl_episode_collection.md](../tutorials/rl_episode_collection.md) | 真机RL：人工回合采集与复位 |
| [tutorials/rl_episode_visual_review.md](../tutorials/rl_episode_visual_review.md) | 真机 RL 回合逐帧可视化与人工检查 |
| [tutorials/robot_3d_replay.md](../tutorials/robot_3d_replay.md) | RViz双臂3D回放＋视觉触觉看板 |
| [tutorials/robot_controller.md](../tutorials/robot_controller.md) | OpticalModule 机械臂控制代码迁移 |
| [tutorials/robot_gamepad_startup.md](../tutorials/robot_gamepad_startup.md) | 机器人接收端与手柄启动步骤 |
| [tutorials/robot_state_dashboard.md](../tutorials/robot_state_dashboard.md) | 旧录包：视觉、触觉与机器人状态同屏 |
| [tutorials/ros_observation_interface.md](../tutorials/ros_observation_interface.md) | 真机 ROS 观测接口（只读） |
| [tutorials/rviz_representative_bags.md](../tutorials/rviz_representative_bags.md) | RViz 操作教程：实时传感器与历代录包 |
| [tutorials/sdk_native_dashboard.md](../tutorials/sdk_native_dashboard.md) | SDK 原生数值看板 |
| [tutorials/sensor_collection.md](../tutorials/sensor_collection.md) | 独立 ROS 传感器：安装、采集、录包与回放 |
| [tutorials/sensor_commands.md](../tutorials/sensor_commands.md) | 腕部相机＋触觉：常用命令速查 |
| [tutorials/sensor_decoupling.md](../tutorials/sensor_decoupling.md) | 独立传感器采集、录制与时间审计 |
| [tutorials/six_keypoint_review.md](../tutorials/six_keypoint_review.md) | 六关键点自动候选与人工审核 |
| [tutorials/stack_shadow.md](../tutorials/stack_shadow.md) | 无关节模型：实时 ROS 影子推理 |
| [tutorials/stand_urdf_review.md](../tutorials/stand_urdf_review.md) | 用新 Stand URDF 对照回放 |
| [tutorials/tactile_grid_transport.md](../tutorials/tactile_grid_transport.md) | 触觉24×16低带宽发布（可选第一版） |
| [tutorials/tactile_guard.md](../tutorials/tactile_guard.md) | USB 插入触觉保护 |
| [tutorials/tactile_reconstruction_migration.md](../tutorials/tactile_reconstruction_migration.md) | 在另一台机器恢复触觉重建并做可视化比对 |
| [tutorials/tactile_warning.md](../tutorials/tactile_warning.md) | 只读触觉阈值预警 |
| [tutorials/training_monitor.md](../tutorials/training_monitor.md) | Actor / Learner 统一训练监控 |
| [tutorials/transition_replay.md](../tutorials/transition_replay.md) | 完整 transition 的磁盘存储与双流导入 |
| [tutorials/troubleshooting.md](../tutorials/troubleshooting.md) | 排障、停止与恢复 |
| [tutorials/wrench_live.md](../tutorials/wrench_live.md) | 双指六维力/力矩：实时查看与完整历史记录 |
| [tutorials/wrench_policy_gamepad.md](../tutorials/wrench_policy_gamepad.md) | 带六维力/力矩的 BC 模型：预览与真机手柄接管 |
| [tutorials/wrist_bag_review.md](../tutorials/wrist_bag_review.md) | bag_004腕部相机＋触觉＋机器人RViz回放 |
| [tutorials/wrist_camera.md](../tutorials/wrist_camera.md) | 腕部相机：采集、ROI/full与查看 |

## 训练状态、机制与决策（27）

| 文件 | 标题 |
| --- | --- |
| [docs/agent/training/README.md](agent/training/README.md) | Training 导航 |
| [docs/agent/training/charter.md](agent/training/charter.md) | Training 长期章程 |
| [docs/agent/training/current.md](agent/training/current.md) | Training 当前摘要 |
| [docs/agent/training/decisions/001-executed-action-replay.md](agent/training/decisions/001-executed-action-replay.md) | 001：回放以最终执行动作为准 |
| [docs/agent/training/decisions/002-dual-stream-replay.md](agent/training/decisions/002-dual-stream-replay.md) | 002：在线与示范双流抽样 |
| [docs/agent/training/decisions/README.md](agent/training/decisions/README.md) | Training 架构决定 |
| [docs/agent/training/evolution/README.md](agent/training/evolution/README.md) | Training 纪传体 |
| [docs/agent/training/evolution/axis-controller-interface.md](agent/training/evolution/axis-controller-interface.md) | 对齐 axis_test 实机动作接口 |
| [docs/agent/training/evolution/bag-bc-shadow.md](agent/training/evolution/bag-bc-shadow.md) | 录包BC初始策略与ROS影子推理 |
| [docs/agent/training/evolution/cached-replay.md](agent/training/evolution/cached-replay.md) | 双池共享内存缓存与全量磁盘索引 |
| [docs/agent/training/evolution/current-stack-history.md](agent/training/evolution/current-stack-history.md) | 当前帧独立与历史通道拼接 |
| [docs/agent/training/evolution/demo-collection-bc.md](agent/training/evolution/demo-collection-bc.md) | 手柄示范录包、动作语义与 BC 数据入口 |
| [docs/agent/training/evolution/disk-replay.md](agent/training/evolution/disk-replay.md) | 磁盘 HIL 经验池 |
| [docs/agent/training/evolution/eef-action-space.md](agent/training/evolution/eef-action-space.md) | 左臂末端增量动作与录包代理标签 |
| [docs/agent/training/evolution/hil-actor-learner.md](agent/training/evolution/hil-actor-learner.md) | 六维真机 HIL 环境、SAC 与 Actor/Learner |
| [docs/agent/training/evolution/hil-serl-reference.md](agent/training/evolution/hil-serl-reference.md) | HIL-SERL 开源任务与 USB 实现参考 |
| [docs/agent/training/evolution/hil-training.md](agent/training/evolution/hil-training.md) | HIL 训练与数据流 |
| [docs/agent/training/evolution/history-online-policy.md](agent/training/evolution/history-online-policy.md) | 在线历史 policy 与可选 wrench |
| [docs/agent/training/evolution/nojoint-stack.md](agent/training/evolution/nojoint-stack.md) | 禁用关节输入的历史拼接模型 |
| [docs/agent/training/evolution/oct_03-experiment-design-summary.md](agent/training/evolution/oct_03-experiment-design-summary.md) | oct_03 模仿学习实验与设计总结 |
| [docs/agent/training/evolution/oct_03-training-log.md](agent/training/evolution/oct_03-training-log.md) | oct_03 训练日志 |
| [docs/agent/training/evolution/policy-action-scaling.md](agent/training/evolution/policy-action-scaling.md) | Policy 动作缩放策略与讨论结论 |
| [docs/agent/training/evolution/real-online-rl.md](agent/training/evolution/real-online-rl.md) | 真机在线 RL：BC 热启动、手柄接管与异步训练 |
| [docs/agent/training/evolution/recorded-pose-replay.md](agent/training/evolution/recorded-pose-replay.md) | 右臂录制位姿的动作转换与回放 |
| [docs/agent/training/evolution/resnet10-history.md](agent/training/evolution/resnet10-history.md) | 冻结 ResNet-10 与历史 GRU |
| [docs/agent/training/evolution/six-keypoint-review.md](agent/training/evolution/six-keypoint-review.md) | 六关键点自动预标注与人工审核工具 |
| [docs/agent/training/evolution/training-monitor.md](agent/training/evolution/training-monitor.md) | 统一训练监控：状态、链路与只读审阅 |

## 训练编年记录（73）

| 文件 | 标题 |
| --- | --- |
| [docs/agent/training/chronicles/2026-10-01-hil-sim-training.md](agent/training/chronicles/2026-10-01-hil-sim-training.md) | 2026-10-01：仿真 HIL 训练链 |
| [docs/agent/training/chronicles/2026-10-01-low-entropy-sac.md](agent/training/chronicles/2026-10-01-low-entropy-sac.md) | 2026-10-01：低熵纯 SAC 策略改善 |
| [docs/agent/training/chronicles/2026-10-01-policy-improvement-audit.md](agent/training/chronicles/2026-10-01-policy-improvement-audit.md) | 2026-10-01：HIL 双流与策略改善审计 |
| [docs/agent/training/chronicles/2026-10-01-training-implementation-docs.md](agent/training/chronicles/2026-10-01-training-implementation-docs.md) | 2026-10-01：训练实现文档核查 |
| [docs/agent/training/chronicles/2026-10-02-disk-replay.md](agent/training/chronicles/2026-10-02-disk-replay.md) | 2026-10-02：磁盘 HIL 经验池与后台预取 |
| [docs/agent/training/chronicles/2026-10-02-hil-serl-reference.md](agent/training/chronicles/2026-10-02-hil-serl-reference.md) | 2026-10-02：HIL-SERL 参考核查与视觉融合勘误 |
| [docs/agent/training/chronicles/2026-10-02-usb-resources-and-network.md](agent/training/chronicles/2026-10-02-usb-resources-and-network.md) | 2026-10-02：USB 资源、Buffer 与总体网络补录 |
| [docs/agent/training/chronicles/2026-10-03-action-bag.md](agent/training/chronicles/2026-10-03-action-bag.md) | 2026-10-03：Float64MultiArray 动作包与模拟控制端联调 |
| [docs/agent/training/chronicles/2026-10-03-bag-bc-shadow.md](agent/training/chronicles/2026-10-03-bag-bc-shadow.md) | 2026-10-03：真实录包BC训练与ROS影子推理第一版 |
| [docs/agent/training/chronicles/2026-10-03-eef-action-space.md](agent/training/chronicles/2026-10-03-eef-action-space.md) | 2026-10-03：bag_004末端动作空间第一版 |
| [docs/agent/training/chronicles/2026-10-03-experiment-data-archive.md](agent/training/chronicles/2026-10-03-experiment-data-archive.md) | 2026-10-03：历史实验数据外置归档（复制完成，迁移暂停） |
| [docs/agent/training/chronicles/2026-10-03-formal-dataset.md](agent/training/chronicles/2026-10-03-formal-dataset.md) | oct3正式录包：有效性检查与训练准备 |
| [docs/agent/training/chronicles/2026-10-03-formal-training-run1.md](agent/training/chronicles/2026-10-03-formal-training-run1.md) | oct3正式录包：首轮训练结果 |
| [docs/agent/training/chronicles/2026-10-03-history-gru-training.md](agent/training/chronicles/2026-10-03-history-gru-training.md) | 2026-10-03：1秒历史GRU训练与单帧对照 |
| [docs/agent/training/chronicles/2026-10-03-intervention-action-contract.md](agent/training/chronicles/2026-10-03-intervention-action-contract.md) | 2026-10-03：HIL-SERL 人工接管与 ROS 动作接口讨论 |
| [docs/agent/training/chronicles/2026-10-03-tactile-bc-archive-complete.md](agent/training/chronicles/2026-10-03-tactile-bc-archive-complete.md) | 2026-10-03：完成tactile和bc迁移，保留eef_bc |
| [docs/agent/training/chronicles/2026-10-03-validation-resplit.md](agent/training/chronicles/2026-10-03-validation-resplit.md) | 2026-10-03：按示教过程调整验证包并重训 |
| [docs/agent/training/chronicles/2026-10-03-wrist-policy-input.md](agent/training/chronicles/2026-10-03-wrist-policy-input.md) | 2026-10-03：腕部策略输入与相机可用性标记 |
| [docs/agent/training/chronicles/2026-10-04-axis-controller-interface.md](agent/training/chronicles/2026-10-04-axis-controller-interface.md) | 2026-10-04：核对 axis_test 实机接口 |
| [docs/agent/training/chronicles/2026-10-04-axis-rotation-assumption.md](agent/training/chronicles/2026-10-04-axis-rotation-assumption.md) | 2026-10-04：暂定基坐标系旋转向量与转换说明 |
| [docs/agent/training/chronicles/2026-10-04-cuda-policy-latency.md](agent/training/chronicles/2026-10-04-cuda-policy-latency.md) | 2026-10-04：独立 CUDA 环境与策略推理时延对照 |
| [docs/agent/training/chronicles/2026-10-04-current-stack-history.md](agent/training/chronicles/2026-10-04-current-stack-history.md) | 2026-10-04：当前帧独立与过去9帧拼接对照 |
| [docs/agent/training/chronicles/2026-10-04-history-online-wrench.md](agent/training/chronicles/2026-10-04-history-online-wrench.md) | 2026-10-04：在线历史推理与 wrench 有效性标签 |
| [docs/agent/training/chronicles/2026-10-04-nojoint-gpu-training.md](agent/training/chronicles/2026-10-04-nojoint-gpu-training.md) | 2026-10-04：禁用关节反馈的GPU训练 |
| [docs/agent/training/chronicles/2026-10-04-policy-gamepad-integration.md](agent/training/chronicles/2026-10-04-policy-gamepad-integration.md) | 2026-10-04：实时 policy、RB 仲裁与 SDK 转换接通 |
| [docs/agent/training/chronicles/2026-10-04-resnet10-history.md](agent/training/chronicles/2026-10-04-resnet10-history.md) | 2026-10-04：下载预训练ResNet-10并重训历史policy |
| [docs/agent/training/chronicles/2026-10-04-six-keypoint-review.md](agent/training/chronicles/2026-10-04-six-keypoint-review.md) | 2026-10-04：六关键点本地候选与人工审核闭环 |
| [docs/agent/training/chronicles/2026-10-04-stack-live-shadow.md](agent/training/chronicles/2026-10-04-stack-live-shadow.md) | 2026-10-04：无关节模型实时影子推理入口与现场阻塞 |
| [docs/agent/training/chronicles/2026-10-05-demo-collection-bc.md](agent/training/chronicles/2026-10-05-demo-collection-bc.md) | 2026-10-05：独立示范采集与命令监督 BC |
| [docs/agent/training/chronicles/2026-10-05-hil-actor-learner.md](agent/training/chronicles/2026-10-05-hil-actor-learner.md) | 2026-10-05：六维真机 HIL、双 Critic 与 Actor/Learner |
| [docs/agent/training/chronicles/2026-10-05-passive-bc-wrench.md](agent/training/chronicles/2026-10-05-passive-bc-wrench.md) | 2026-10-05：四个真实日期包转换与wrench BC训练 |
| [docs/agent/training/chronicles/2026-10-05-passive-demo-audit.md](agent/training/chronicles/2026-10-05-passive-demo-audit.md) | 2026-10-05：独立手柄四包检查与真实指令可视化 |
| [docs/agent/training/chronicles/2026-10-05-policy-input-audit-no-wrench.md](agent/training/chronicles/2026-10-05-policy-input-audit-no-wrench.md) | 2026-10-05：现场后退诊断、推理录制与无wrench对照 |
| [docs/agent/training/chronicles/2026-10-05-session-documentation-audit.md](agent/training/chronicles/2026-10-05-session-documentation-audit.md) | 2026-10-05：本窗口开发记录覆盖核查 |
| [docs/agent/training/chronicles/2026-10-05-transition-replay.md](agent/training/chronicles/2026-10-05-transition-replay.md) | 2026-10-05：完整 transition 磁盘导入与在线分流 API |
| [docs/agent/training/chronicles/2026-10-06-rl-episode-collection-audit.md](agent/training/chronicles/2026-10-06-rl-episode-collection-audit.md) | 2026-10-06：真机RL回合采集、异步写盘与首批数据检查 |
| [docs/agent/training/chronicles/2026-10-07-alternating-rl.md](agent/training/chronicles/2026-10-07-alternating-rl.md) | 2026-10-07：按回合交替 RL 最小闭环 |
| [docs/agent/training/chronicles/2026-10-07-async-gamepad-home-gripper-fix.md](agent/training/chronicles/2026-10-07-async-gamepad-home-gripper-fix.md) | 2026-10-07：异步 RL 手柄 Back 回 home 与 A/B 夹爪修复 |
| [docs/agent/training/chronicles/2026-10-07-async-rl.md](agent/training/chronicles/2026-10-07-async-rl.md) | 2026-10-07：异步Actor/Learner及10回合策略刷新 |
| [docs/agent/training/chronicles/2026-10-07-bc-protected-rl-and-encoder.md](agent/training/chronicles/2026-10-07-bc-protected-rl-and-encoder.md) | 2026-10-07：BC保护式RL、模型选择与编码器冻结范围 |
| [docs/agent/training/chronicles/2026-10-07-dual-replay.md](agent/training/chronicles/2026-10-07-dual-replay.md) | 2026-10-07：独立示范/在线双池与固定初始示范 |
| [docs/agent/training/chronicles/2026-10-07-human-periodic-collection.md](agent/training/chronicles/2026-10-07-human-periodic-collection.md) | 2026-10-07：人工周期采集现场联调与多回合操作 |
| [docs/agent/training/chronicles/2026-10-07-new-bc-to-rl-handoff.md](agent/training/chronicles/2026-10-07-new-bc-to-rl-handoff.md) | 2026-10-07：新示范、BC 推理与下一步 RL 交接 |
| [docs/agent/training/chronicles/2026-10-07-new-periodic-human-bc.md](agent/training/chronicles/2026-10-07-new-periodic-human-bc.md) | 2026-10-07：新采人工周期数据的两阶段 BC 训练 |
| [docs/agent/training/chronicles/2026-10-07-periodic-replay-bc-fitting.md](agent/training/chronicles/2026-10-07-periodic-replay-bc-fitting.md) | 2026-10-07：周期控制、成功动作回放与 BC 拟合诊断 |
| [docs/agent/training/chronicles/2026-10-07-shared-serl-resume.md](agent/training/chronicles/2026-10-07-shared-serl-resume.md) | 2026-10-07：共享编码器、HIL-SERL 对齐与中断恢复 |
| [docs/agent/training/chronicles/2026-10-08-first-online-rl-run.md](agent/training/chronicles/2026-10-08-first-online-rl-run.md) | 2026-10-08：新 BC 热启动后的首批真机在线 RL 与 EEF 时序审计 |
| [docs/agent/training/chronicles/2026-10-09-arbitration-modes.md](agent/training/chronicles/2026-10-09-arbitration-modes.md) | 2026-10-09：推理完成后仲裁成为异步 RL 默认 |
| [docs/agent/training/chronicles/2026-10-09-local-data-relocation.md](agent/training/chronicles/2026-10-09-local-data-relocation.md) | 2026-10-09：local 冷数据迁到 omi_proj_data/local |
| [docs/agent/training/chronicles/2026-10-09-observation-driven-control.md](agent/training/chronicles/2026-10-09-observation-driven-control.md) | 2026-10-09：观测驱动动作与时序仅诊断 |
| [docs/agent/training/chronicles/2026-10-09-rl-episode-visual-review.md](agent/training/chronicles/2026-10-09-rl-episode-visual-review.md) | 2026-10-09：真机 RL 原始回合逐帧查看 |
| [docs/agent/training/chronicles/2026-10-09-rl-training-storage-migration.md](agent/training/chronicles/2026-10-09-rl-training-storage-migration.md) | 2026-10-09：`local/rl_training` 占用与迁移可行性核查 |
| [docs/agent/training/chronicles/2026-10-09-sdk-rejection-and-handoff-audit.md](agent/training/chronicles/2026-10-09-sdk-rejection-and-handoff-audit.md) | 2026-10-09：首次新仲裁试跑的 SDK 拒绝与通道切换排查 |
| [docs/agent/training/chronicles/2026-10-09-start-history-retention.md](agent/training/chronicles/2026-10-09-start-history-retention.md) | 2026-10-09：Start 保留 SAC 十帧输入历史 |
| [docs/agent/training/chronicles/2026-10-09-training-monitor.md](agent/training/chronicles/2026-10-09-training-monitor.md) | 2026-10-09：Actor / Learner 统一训练监控 |
| [docs/agent/training/chronicles/2026-10-10-cached-dual-replay.md](agent/training/chronicles/2026-10-10-cached-dual-replay.md) | 2026-10-10：共享内存 Demo/RL 双池实现与真实数据验证 |
| [docs/agent/training/chronicles/2026-10-10-fixed-bc-storage-live-review.md](agent/training/chronicles/2026-10-10-fixed-bc-storage-live-review.md) | 2026-10-10：固定 BC12045 现场运行、单帧存储与 EEF 检查 |
| [docs/agent/training/chronicles/2026-10-10-observation-frame-storage.md](agent/training/chronicles/2026-10-10-observation-frame-storage.md) | 2026-10-10：async RL 回合观测按单帧存储 |
| [docs/agent/training/chronicles/2026-10-10-old-and-sdk-episode-archive.md](agent/training/chronicles/2026-10-10-old-and-sdk-episode-archive.md) | 2026-10-10：旧格式与 SDK 错误回合迁移 |
| [docs/agent/training/chronicles/2026-10-10-recorded-bc-learner-validation.md](agent/training/chronicles/2026-10-10-recorded-bc-learner-validation.md) | 2026-10-10：单帧 BC 录制到 Learner 的离线验证 |
| [docs/agent/training/chronicles/2026-10-11-30s-buffer-dashboard.md](agent/training/chronicles/2026-10-11-30s-buffer-dashboard.md) | 2026-10-11：原BC权重、新数据目录、30秒回合与双池可视化 |
| [docs/agent/training/chronicles/2026-10-11-batch64-exploration-live.md](agent/training/chronicles/2026-10-11-batch64-exploration-live.md) | 2026-10-11：batch64在线训练与探索噪声现场核验 |
| [docs/agent/training/chronicles/2026-10-11-cached-offline-exp01.md](agent/training/chronicles/2026-10-11-cached-offline-exp01.md) | 2026-10-11：缓存门槛修正与第一轮有界离线实验 |
| [docs/agent/training/chronicles/2026-10-11-cached-online-start.md](agent/training/chronicles/2026-10-11-cached-online-start.md) | 2026-10-11：新缓存在线采集与训练会话启动 |
| [docs/agent/training/chronicles/2026-10-11-critic-diagnostics.md](agent/training/chronicles/2026-10-11-critic-diagnostics.md) | 2026-10-11：Critic负Q与稀疏成功监督的离线诊断 |
| [docs/agent/training/chronicles/2026-10-11-external-archive-restore.md](agent/training/chronicles/2026-10-11-external-archive-restore.md) | 2026-10-11：外盘归档与真实buffer恢复验证 |
| [docs/agent/training/chronicles/2026-10-11-invalid-data-reset.md](agent/training/chronicles/2026-10-11-invalid-data-reset.md) | 2026-10-11：问题采集数据归档，原路径恢复BC空池会话 |
| [docs/agent/training/chronicles/2026-10-11-online-exploration.md](agent/training/chronicles/2026-10-11-online-exploration.md) | 2026-10-11：在线策略探索与Actor换权重 |
| [docs/agent/training/chronicles/2026-10-11-runnable-baseline.md](agent/training/chronicles/2026-10-11-runnable-baseline.md) | 2026-10-11：在线HIL RL可运行基线 |
| [docs/agent/training/chronicles/2026-10-11-tactile-gamma-pending.md](agent/training/chronicles/2026-10-11-tactile-gamma-pending.md) | 2026-10-11：待改项——触觉编码器训练与长回合奖励折扣 |
| [docs/agent/training/chronicles/2026-10-11-weights-only-new-data.md](agent/training/chronicles/2026-10-11-weights-only-new-data.md) | 2026-10-11：只继承BC权重，全部训练数据从新会话采集 |
| [docs/agent/training/chronicles/README.md](agent/training/chronicles/README.md) | Training 编年索引 |
| [docs/agent/training/chronicles/2026-10-12-documentation-consolidation.md](agent/training/chronicles/2026-10-12-documentation-consolidation.md) | 2026-10-12：操作说明汇总与纪传/编年同步 |


## 接口与存储契约（7）

| 文件 | 标题 |
| --- | --- |
| [docs/agent/interfaces/README.md](agent/interfaces/README.md) | 接口总索引 |
| [docs/agent/interfaces/cli.md](agent/interfaces/cli.md) | CLI 入口 |
| [docs/agent/interfaces/data-formats.md](agent/interfaces/data-formats.md) | 数据格式与单位 |
| [docs/agent/interfaces/external-systems.md](agent/interfaces/external-systems.md) | 外部系统与参考边界 |
| [docs/agent/interfaces/local-resources.md](agent/interfaces/local-resources.md) | 本地资源定位 |
| [docs/agent/interfaces/local-storage.md](agent/interfaces/local-storage.md) | local 大数据存储与外接盘路径 |
| [docs/agent/interfaces/python-modules.md](agent/interfaces/python-modules.md) | Python 模块与边界 |

## 硬件状态与历史（72）

| 文件 | 标题 |
| --- | --- |
| [docs/agent/hardware/README.md](agent/hardware/README.md) | Hardware 导航 |
| [docs/agent/hardware/charter.md](agent/hardware/charter.md) | Hardware 长期章程 |
| [docs/agent/hardware/chronicles/2026-10-01-sdk-boundary.md](agent/hardware/chronicles/2026-10-01-sdk-boundary.md) | 2026-10-01：SDK 边界与模拟测试 |
| [docs/agent/hardware/chronicles/2026-10-02-camera-roi-and-tactile-review.md](agent/hardware/chronicles/2026-10-02-camera-roi-and-tactile-review.md) | 2026-10-02：相机 ROI 双版本可视化与触觉输入核查 |
| [docs/agent/hardware/chronicles/2026-10-02-camera-tactile-dashboard.md](agent/hardware/chronicles/2026-10-02-camera-tactile-dashboard.md) | 2026-10-02：相机和触觉合并显示 |
| [docs/agent/hardware/chronicles/2026-10-02-native-record-review.md](agent/hardware/chronicles/2026-10-02-native-record-review.md) | 2026-10-02：新录包检查、原生字段看板与末端坐标核查 |
| [docs/agent/hardware/chronicles/2026-10-02-robot-3d-replay.md](agent/hardware/chronicles/2026-10-02-robot-3d-replay.md) | 2026-10-02：从文字状态到RViz双臂3D回放 |
| [docs/agent/hardware/chronicles/2026-10-02-robot-state-dashboard.md](agent/hardware/chronicles/2026-10-02-robot-state-dashboard.md) | 2026-10-02：旧录包机器人状态同屏 |
| [docs/agent/hardware/chronicles/2026-10-02-ros-observation.md](agent/hardware/chronicles/2026-10-02-ros-observation.md) | 2026-10-02：ROS 多模态观测接口与 record010 验证 |
| [docs/agent/hardware/chronicles/2026-10-02-sdk-native-dashboard.md](agent/hardware/chronicles/2026-10-02-sdk-native-dashboard.md) | 2026-10-02：独立 SDK 原生数值看板 |
| [docs/agent/hardware/chronicles/2026-10-02-sensor-collection.md](agent/hardware/chronicles/2026-10-02-sensor-collection.md) | 2026-10-02：独立 ROS 传感器采集、录包与回放 |
| [docs/agent/hardware/chronicles/2026-10-02-stable-viewer-policy-audit.md](agent/hardware/chronicles/2026-10-02-stable-viewer-policy-audit.md) | 2026-10-02：保护稳定看板及 ROS→策略输入核查 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-field-semantics.md](agent/hardware/chronicles/2026-10-02-tactile-field-semantics.md) | 2026-10-02：触觉 deformation/shear 字段语义与实现边界 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-identity-confirmation.md](agent/hardware/chronicles/2026-10-02-tactile-identity-confirmation.md) | 2026-10-02：双指逻辑侧与 serial 外部确认 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-live-replay.md](agent/hardware/chronicles/2026-10-02-tactile-live-replay.md) | 2026-10-02：rosbag 实时触觉向量回放 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-offline-reconstruction.md](agent/hardware/chronicles/2026-10-02-tactile-offline-reconstruction.md) | 2026-10-02：record010 无 serial 离线触觉场重建 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-preview-layout.md](agent/hardware/chronicles/2026-10-02-tactile-preview-layout.md) | 2026-10-02：触觉预览与原图布局调整 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-reconstruction-migration.md](agent/hardware/chronicles/2026-10-02-tactile-reconstruction-migration.md) | 2026-10-02：触觉图像重建适配器与 SDK 本地归档迁移 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-resolution-and-throughput.md](agent/hardware/chronicles/2026-10-02-tactile-resolution-and-throughput.md) | 2026-10-02：触觉分辨率、预训练编码与30 Hz采集讨论 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-terminology.md](agent/hardware/chronicles/2026-10-02-tactile-terminology.md) | 2026-10-02：触觉表示名称统一 |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-vector-renderer.md](agent/hardware/chronicles/2026-10-02-tactile-vector-renderer.md) | 2026-10-02：OMI 触觉向量箭头 renderer |
| [docs/agent/hardware/chronicles/2026-10-02-tactile-zero-load-baseline.md](agent/hardware/chronicles/2026-10-02-tactile-zero-load-baseline.md) | 2026-10-02：record010 零载荷触觉基准提取 |
| [docs/agent/hardware/chronicles/2026-10-02-wrist-viewer-followup.md](agent/hardware/chronicles/2026-10-02-wrist-viewer-followup.md) | 2026-10-02：腕部相机需求澄清与可视化遗留 |
| [docs/agent/hardware/chronicles/2026-10-03-daimon-live-stream-stutter.md](agent/hardware/chronicles/2026-10-03-daimon-live-stream-stutter.md) | 2026-10-03：腕部真实出图与视频流卡顿遗留 |
| [docs/agent/hardware/chronicles/2026-10-03-daimon-live.md](agent/hardware/chronicles/2026-10-03-daimon-live.md) | 2026-10-03：真实触觉接通与腕部实时入口 |
| [docs/agent/hardware/chronicles/2026-10-03-day-checkpoint.md](agent/hardware/chronicles/2026-10-03-day-checkpoint.md) | 2026-10-03：阶段性版本检查点 |
| [docs/agent/hardware/chronicles/2026-10-03-grid-bag-review-and-raw-deferred.md](agent/hardware/chronicles/2026-10-03-grid-bag-review-and-raw-deferred.md) | 2026-10-03：小矩阵实录回放、raw缺失解释与开发暂缓 |
| [docs/agent/hardware/chronicles/2026-10-03-grid-general-viewer.md](agent/hardware/chronicles/2026-10-03-grid-general-viewer.md) | 2026-10-03：通用小矩阵RViz回放入口 |
| [docs/agent/hardware/chronicles/2026-10-03-raw-wrench-opt-in.md](agent/hardware/chronicles/2026-10-03-raw-wrench-opt-in.md) | 2026-10-03：grid模式raw与wrench显式开关 |
| [docs/agent/hardware/chronicles/2026-10-03-roi-stream-plan.md](agent/hardware/chronicles/2026-10-03-roi-stream-plan.md) | 2026-10-03：共享内存结论边界与策略ROI传输方案 |
| [docs/agent/hardware/chronicles/2026-10-03-sensor-tutorial-triad.md](agent/hardware/chronicles/2026-10-03-sensor-tutorial-triad.md) | 2026-10-03：传感器教程三件套 |
| [docs/agent/hardware/chronicles/2026-10-03-stand-axis-correction.md](agent/hardware/chronicles/2026-10-03-stand-axis-correction.md) | 2026-10-03：Stand 模型对照、关节方向修正与命名归档 |
| [docs/agent/hardware/chronicles/2026-10-03-tactile-depth-wrench-flags.md](agent/hardware/chronicles/2026-10-03-tactile-depth-wrench-flags.md) | 2026-10-03：触觉深度与六维力启动开关 |
| [docs/agent/hardware/chronicles/2026-10-03-tactile-grid-transport.md](agent/hardware/chronicles/2026-10-03-tactile-grid-transport.md) | 2026-10-03：触觉数值场24×16可选传输 |
| [docs/agent/hardware/chronicles/2026-10-03-tactile-numeric-default.md](agent/hardware/chronicles/2026-10-03-tactile-numeric-default.md) | 2026-10-03：独立触觉采集默认改为低带宽完整数值输入 |
| [docs/agent/hardware/chronicles/2026-10-03-wrench-unframed-fix.md](agent/hardware/chronicles/2026-10-03-wrench-unframed-fix.md) | 2026-10-03：修复SDK无帧号六维力被省略 |
| [docs/agent/hardware/chronicles/2026-10-03-wrist-roi-and-capture-followup.md](agent/hardware/chronicles/2026-10-03-wrist-roi-and-capture-followup.md) | 2026-10-03：bag_004腕部回放、ROI基线及采集遗留 |
| [docs/agent/hardware/chronicles/2026-10-03-wrist-roi-topic.md](agent/hardware/chronicles/2026-10-03-wrist-roi-topic.md) | 2026-10-03：腕部原图/ROI发布开关 |
| [docs/agent/hardware/chronicles/2026-10-03-wrist-shm-trial.md](agent/hardware/chronicles/2026-10-03-wrist-shm-trial.md) | 2026-10-03：腕部大图共享内存传输实验 |
| [docs/agent/hardware/chronicles/2026-10-03-wrist-stream-investigation-summary.md](agent/hardware/chronicles/2026-10-03-wrist-stream-investigation-summary.md) | 2026-10-03：视频流问题排查与解决过程归档 |
| [docs/agent/hardware/chronicles/2026-10-03-wrist-topic-question.md](agent/hardware/chronicles/2026-10-03-wrist-topic-question.md) | 2026-10-03：腕部相机准确话题名称核查与议题暂缓 |
| [docs/agent/hardware/chronicles/2026-10-04-gamepad-intervention.md](agent/hardware/chronicles/2026-10-04-gamepad-intervention.md) | 2026-10-04：手柄六维控制与 RB 接管首版 |
| [docs/agent/hardware/chronicles/2026-10-04-grid-live-review.md](agent/hardware/chronicles/2026-10-04-grid-live-review.md) | 2026-10-04：实时grid观测RViz看板 |
| [docs/agent/hardware/chronicles/2026-10-04-live-rviz-checkpoint.md](agent/hardware/chronicles/2026-10-04-live-rviz-checkpoint.md) | 2026-10-04：实时 RViz 阶段总结与 EEF 对齐遗留 |
| [docs/agent/hardware/chronicles/2026-10-05-control-velocity-hold.md](agent/hardware/chronicles/2026-10-05-control-velocity-hold.md) | 2026-10-05 手柄、策略速度保持与夹爪启用修复 |
| [docs/agent/hardware/chronicles/2026-10-05-rgb-clock-and-receive-age.md](agent/hardware/chronicles/2026-10-05-rgb-clock-and-receive-age.md) | 2026-10-05：外部RGB时钟与接收年龄排查 |
| [docs/agent/hardware/chronicles/2026-10-05-robot-controller-migration.md](agent/hardware/chronicles/2026-10-05-robot-controller-migration.md) | 2026-10-05：OpticalModule 控制接收端迁移 |
| [docs/agent/hardware/chronicles/2026-10-05-sensor-decoupling.md](agent/hardware/chronicles/2026-10-05-sensor-decoupling.md) | 2026-10-05：触觉独立字段与腕部录制队列 |
| [docs/agent/hardware/chronicles/2026-10-05-wrench-live-recording.md](agent/hardware/chronicles/2026-10-05-wrench-live-recording.md) | 2026-10-05：双指六维力/力矩实时显示与历史记录 |
| [docs/agent/hardware/chronicles/2026-10-07-eef-mount-and-view.md](agent/hardware/chronicles/2026-10-07-eef-mount-and-view.md) | 2026-10-07：左臂 EEF 安装平移修正与实时显示补偿移除 |
| [docs/agent/hardware/chronicles/2026-10-07-grid-camera-receive-freshness.md](agent/hardware/chronicles/2026-10-07-grid-camera-receive-freshness.md) | 2026-10-07：实时grid看板外部RGB按接收时间显示 |
| [docs/agent/hardware/chronicles/2026-10-07-rviz-bag-relocation.md](agent/hardware/chronicles/2026-10-07-rviz-bag-relocation.md) | 2026-10-07：RViz代表录包集中与历史文件外置 |
| [docs/agent/hardware/chronicles/README.md](agent/hardware/chronicles/README.md) | Hardware 编年索引 |
| [docs/agent/hardware/current.md](agent/hardware/current.md) | Hardware 当前摘要 |
| [docs/agent/hardware/decisions/001-readonly-motion-gate.md](agent/hardware/decisions/001-readonly-motion-gate.md) | 001：默认只读与显式运动门 |
| [docs/agent/hardware/decisions/README.md](agent/hardware/decisions/README.md) | Hardware 架构决定 |
| [docs/agent/hardware/evolution/README.md](agent/hardware/evolution/README.md) | Hardware 纪传体 |
| [docs/agent/hardware/evolution/gamepad-control.md](agent/hardware/evolution/gamepad-control.md) | 手柄末端控制与 SDK 坐标适配：开发记录 |
| [docs/agent/hardware/evolution/grid-live-review.md](agent/hardware/evolution/grid-live-review.md) | 实时小矩阵观测看板 |
| [docs/agent/hardware/evolution/robot-3d-replay.md](agent/hardware/evolution/robot-3d-replay.md) | 机器人3D录包回放 |
| [docs/agent/hardware/evolution/robot-controller.md](agent/hardware/evolution/robot-controller.md) | OpticalModule 控制架构与接收端迁移 |
| [docs/agent/hardware/evolution/ros-observation.md](agent/hardware/evolution/ros-observation.md) | ROS 多模态观测接口 |
| [docs/agent/hardware/evolution/sdk-native-dashboard.md](agent/hardware/evolution/sdk-native-dashboard.md) | SDK 原生数值看板 |
| [docs/agent/hardware/evolution/sensor-collection.md](agent/hardware/evolution/sensor-collection.md) | 独立传感器采集与回放 |
| [docs/agent/hardware/evolution/sensor-decoupling.md](agent/hardware/evolution/sensor-decoupling.md) | 触觉与腕部采集解耦：实现方法与边界 |
| [docs/agent/hardware/evolution/sensor-time-alignment.md](agent/hardware/evolution/sensor-time-alignment.md) | RGB与触觉的时间基准、接收新鲜度和策略检查 |
| [docs/agent/hardware/evolution/tactile-live.md](agent/hardware/evolution/tactile-live.md) | rosbag 播放时的触觉向量显示 |
| [docs/agent/hardware/evolution/tactile-reconstruction-migration.md](agent/hardware/evolution/tactile-reconstruction-migration.md) | 图像重建接口迁移：当前方案 |
| [docs/agent/hardware/evolution/tactile-resolution-and-throughput.md](agent/hardware/evolution/tactile-resolution-and-throughput.md) | 触觉分辨率、策略编码与采集吞吐 |
| [docs/agent/hardware/evolution/tianji-adapter.md](agent/hardware/evolution/tianji-adapter.md) | Tianji SDK 适配器 |
| [docs/agent/hardware/evolution/wrench-live.md](agent/hardware/evolution/wrench-live.md) | 双指wrench实时显示与持久历史 |
| [docs/agent/hardware/evolution/wrist-stream-performance.md](agent/hardware/evolution/wrist-stream-performance.md) | 腕部视频流卡顿：排查、传输改善与ROI发布 |

## 仿真状态与历史（10）

| 文件 | 标题 |
| --- | --- |
| [docs/agent/simulation/README.md](agent/simulation/README.md) | Simulation 导航 |
| [docs/agent/simulation/charter.md](agent/simulation/charter.md) | Simulation 长期章程 |
| [docs/agent/simulation/chronicles/2026-10-01-a-arm-reach.md](agent/simulation/chronicles/2026-10-01-a-arm-reach.md) | 2026-10-01：A 臂末端到达仿真闭环 |
| [docs/agent/simulation/chronicles/2026-10-01-omi-environment.md](agent/simulation/chronicles/2026-10-01-omi-environment.md) | 2026-10-01：OMI 本地仿真环境配置 |
| [docs/agent/simulation/chronicles/README.md](agent/simulation/chronicles/README.md) | Simulation 编年索引 |
| [docs/agent/simulation/current.md](agent/simulation/current.md) | Simulation 当前摘要 |
| [docs/agent/simulation/decisions/001-external-scene.md](agent/simulation/decisions/001-external-scene.md) | 001：外部场景显式装载 |
| [docs/agent/simulation/decisions/README.md](agent/simulation/decisions/README.md) | Simulation 架构决定 |
| [docs/agent/simulation/evolution/README.md](agent/simulation/evolution/README.md) | Simulation 纪传体 |
| [docs/agent/simulation/evolution/model-and-task.md](agent/simulation/evolution/model-and-task.md) | 模型与 A 臂到达任务 |

## 设计文档（7）

| 文件 | 标题 |
| --- | --- |
| [docs/design/README.md](design/README.md) | 设计文档 |
| [docs/design/bag-bc-shadow-policy.md](design/bag-bc-shadow-policy.md) | 录包行为克隆与ROS影子推理：第一版目标 |
| [docs/design/camera-roi-v1.md](design/camera-roi-v1.md) | 双相机 ROI 选择约定：第一版 |
| [docs/design/documentation-system.md](design/documentation-system.md) | 文档体系与维护规则 |
| [docs/design/hil-architecture.md](design/hil-architecture.md) | OMI HIL RL 跨领域架构 |
| [docs/design/ros-to-policy-integration.md](design/ros-to-policy-integration.md) | ROS 到真机策略输入：当前缺口与实施方案 |
| [docs/design/tactile-observation-requirements.md](design/tactile-observation-requirements.md) | 真机触觉观测、录制与可视化验证需求 |

## 项目根目录、组件与其他说明（7）

| 文件 | 标题 |
| --- | --- |
| [CONTEXT.md](../CONTEXT.md) | OMI 领域术语 |
| [PROMPTS/documentation_organizer.md](../PROMPTS/documentation_organizer.md) | 通用项目文档整理 Prompt |
| [README.md](../README.md) | OMI：天机机械臂 Human-in-the-Loop RL |
| [manifests/README.md](../manifests/README.md) | 本地资源清单 |
| [ros2/arm_delta_cmd/README.md](../ros2/arm_delta_cmd/README.md) | OMI 机械臂增量控制接收端 |
| [ros2/marker_detect/hand_eye_calibration_principle.md](../ros2/marker_detect/hand_eye_calibration_principle.md) | 手眼标定原理说明 |
| [third_party/serl/NOTICE.md](../third_party/serl/NOTICE.md) | SERL architecture reference |
