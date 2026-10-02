# 能力总表

证据等级：**代码/静态**、**自动测试**、**headless 仿真**、**人工 GUI 观察**、**设备只读**、**真机运动**。以下状态仅针对 OMI 当前代码。

| 能力 | 当前入口 | 已验证 | 尚未验证 |
| --- | --- | --- | --- |
| A 臂 MJCF 加载和任务预检 | `python -m omi_hil_rl.sim.preflight --scene ...` | 外部场景在本机加载；headless 仿真与自动测试 | 现场模型、工具和 TCP 一致性 |
| A 臂末端到达任务 | `TianjiAReachEnv` | 目标可达；策略独立评估 30/30（固定简单目标） | 真实设备、视觉变化和扰动 |
| 代理模型接口测试 | `TianjiSurrogateEnv`、`sim.smoke` | 自动测试 | 代理动力学代表性 |
| 键盘逐关节点动与 JSONL | `sim.keyboard_teleop` | 解析和记录接口自动测试；脚本示范实际运行 | 人工键盘操作的现场体验、连续遥操作 |
| 策略运行中键盘接管 | `sim.interactive_rollout` | 2 步命令行回归：1 条人类、1 条策略 transition；校验通过 | 连续低延迟接管 |
| 脚本接管与动作仲裁 | `ScriptedInterventionWrapper`、环境 `step` | 自动测试；headless 训练 | 真人在线接管延迟 |
| 奖励与回合结束 | 环境 progress/sparse 模式 | 训练进度奖励；独立评估稀疏成功奖励；TCP 阈值和超时已在仿真运行 | 视觉奖励、真机任务奖励、碰撞/力惩罚 |
| SAC 训练、HIL 双流回放、示范导入 | `training.sim_train` | 1500 步仿真训练；7 条离线示范导入；双流采样和环形覆盖测试 | LeRobot actor/learner、真机在线训练 |
| 磁盘回放、预取与恢复 | `DiskHILReplayBuffer`、`--replay-backend disk` | 图像/状态自动测试；A 臂 200 步；缓存 batch 基准 | 超内存冷盘性能、长时采集、真机时限 |
| Policy improvement 审计 | `policy_progress.jsonl`、`training.plot_progress` | SAC+BC 0/10 → 10/10；低熵纯 SAC 0/10 → 10/10，另取 30 回合 30/30；默认熵纯 SAC 对照失败 | 原版分布式实现与跨目标泛化 |
| 录制格式校验与独立评估 | `validate_recording`、`sim_eval` | 1500 条记录校验；30 回合评估 | 长期统计泛化 |
| MuJoCo 离屏可视化 | `sim.visualize` | EGL 离屏渲染；PNG/GIF 已生成 | MuJoCo GUI/Viewer 人工观察 |
| 真机 ROS 多模态只读观测 | `real.ros_bag_preflight`、`real.ros_observation_live` | `record010` 产生 269 个有效 observation；专项测试 8 passed | 在线 ROS 图、真机时延与策略集成 |
| 相机 ROI/RViz 辅助显示 | `../ros2_camera_clip_tools/view_camera_clip*.sh` | 原图/128、独立 512 与双进程模式；用户人工观察 | 真机在线相机、端到端延迟与长期性能 |
| Tianji SDK A/B 适配 | `TianjiSdkArm` | 假 SDK、MuJoCo SDK 替身自动测试 | 设备只读连接、真机运动、故障现场验收 |

当前自动测试为 **41 passed**（外部 MJCF 环境变量已配置）；前阶段测试数字保留在历史编年记录。四项训练机制见 [训练纪传体](agent/training/evolution/hil-training.md)，磁盘验证见 [开发编年](agent/training/chronicles/2026-10-02-disk-replay.md)，完整对照见 [HIL RL 审计](hil_rl_reproduction.md)。当前仓库未提供真机可执行入口；SDK 适配器默认无运动授权。
