# OMI 文档总目录

最新真机RL采集阶段：[实现与首批数据检查](agent/training/chronicles/2026-10-06-rl-episode-collection-audit.md)
→ [采集操作教程](../tutorials/rl_episode_collection.md)。已采16段1723条并通过结构校验，成功标签待确认，短按漏检未修复；未启动在线RL训练。

当前policy阶段：[现场后退诊断、录制与无wrench训练对照](agent/training/chronicles/2026-10-05-policy-input-audit-no-wrench.md)
→ [无wrench推理与Ctrl+C保存教程](../tutorials/no_wrench_policy_record.md)。已完成BC与用户现场尝试，方向问题仍未解决。

当前[独立手柄录包、检查与逐帧查看](../tutorials/demo_bag_dataset.md) → [四个真实bag检查记录](agent/training/chronicles/2026-10-05-passive-demo-audit.md)。第三包335条真实指令配对已可查看，支持左右键切帧；六维力/力矩位于触觉列顶部。

[采集数据契约与 BC 入口](agent/training/evolution/demo-collection-bc.md) → [采集、指令标签和训练教程](../tutorials/demo_collection_bc.md)。区分独立录包、集成collector和零动作诊断；本批真实BC结果以上述最新阶段记录为准，尚无闭环成功率。

新增六维真机HIL、无夹爪SAC与Actor/Learner：[当前进展与验证边界](agent/training/evolution/hil-actor-learner.md) → [操作教程](../tutorials/hil_actor_learner.md)。三项软件实现已完成，处于真机联调前阶段。

双指六维力/力矩：[实时查看与完整历史记录](../tutorials/wrench_live.md)。

控制接收端已迁入：[迁移与构建教程](../tutorials/robot_controller.md) → [架构及执行语义](agent/hardware/evolution/robot-controller.md)。

实时检查现场topic：[实时小矩阵RViz看板](../tutorials/grid_live_review.md)，独立于录包回放。


新增[六关键点自动候选与人工审核工具](../tutorials/six_keypoint_review.md)，用于独立关键点标注，不改变policy。

末端动作开发：[bag_004操作教程](../tutorials/eef_action_space.md) → [版本契约与验证边界](agent/training/evolution/eef-action-space.md)。

本项目目前是天机 Marvin **A 臂（左臂）**的 MuJoCo HIL RL 原型。当前状态以 [能力总表](capabilities.md) 和各领域 `current.md` 为准；历史实验数字保存在编年记录中。

## 选择入口

| 读者 | 从这里开始 |
| --- | --- |
| 第一次运行 | [环境准备](../tutorials/environment_setup.md) → [最短仿真案例](../tutorials/quickstart.md) |
| 换机器/核对额外依赖 | [额外拷贝与重新安装清单](../tutorials/machine_transfer_checklist.md) |
| SDK原生采集与看板 | [独立采集](../tutorials/sensor_collection.md) → [新数值看板](../tutorials/sdk_native_dashboard.md) |
| record001机器人/末端对照 | [Stand方向修正版](../tutorials/corrected_stand_review.md) → [版本选择及模型限制](agent/hardware/evolution/robot-3d-replay.md#入口选择与当前结论) |
| 操作键盘示范或回放 | [键盘示范](../tutorials/keyboard_demonstration.md) → [录制与训练](../tutorials/recording_and_replay.md) |
| 核查 HIL RL 四项复现 | [训练、干预、buffer、policy improvement 审计](hil_rl_reproduction.md) |
| 理解当前训练实现 | [干预、奖励、策略更新与 Buffer](agent/training/evolution/hil-training.md) |
| 录包训练BC与模拟在线推理 | [操作教程](../tutorials/bag_bc_shadow.md) → [当前能力及限制](agent/training/evolution/bag-bc-shadow.md) |
| 使用磁盘经验池 | [操作教程](../tutorials/disk_replay.md) → [存储与恢复机制](agent/training/evolution/disk-replay.md) |
| 理解原版 HIL-SERL | [开源任务、USB、SpaceMouse、观测与视觉网络](agent/training/evolution/hil-serl-reference.md) |
| 开发与维护 | [Agent 知识库](agent/README.md) → [接口索引](agent/interfaces/README.md) |
| 理解边界 | [安全与副作用](safety.md) → [跨领域设计](design/hil-architecture.md) |
| 规划和验收真机触觉数据 | [触觉观测、录制与可视化验证需求](design/tactile-observation-requirements.md) |
| 播包时查看触觉箭头 | [操作入口](../tutorials/ros_observation_interface.md#播放时实时查看触觉向量) → [当前机制](agent/hardware/evolution/tactile-live.md) |
| 同屏查看相机和触觉 | [原图、128 ROI 与双指向量](../tutorials/ros_observation_interface.md#同时查看相机与触觉) |
| 查找 OMI 之外的工具和资源 | [工作区总索引](../../README.md) → [本地资源接口](agent/interfaces/local-resources.md) |

现有 [A 臂实验报告](a_arm_reach.md) 保存可复现实验与证据；[早期技术调查](tianji_hil_rl.md) 保留当时的 SDK 和参考项目分析。功能的**当前事实**由 `agent/*/evolution/` 维护，避免把早期计划误认为现状。

同级的 `ros2_camera_clip_tools/`、参考仓库、厂商 SDK 和工作区外数据统一由
[工作区总索引](../../README.md)登记；不要只在某篇专题文档中留下无法反向发现的路径。
