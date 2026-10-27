> 历史资料：原路径 `docs/capabilities.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../current.md)；本页保留原过程与证据。

# 能力总表

2026-10-17：[控制响应实测与开发快照](../records/oct17_development_checkpoint.md)。200 Hz/模式3下四段记录确认全零后约0.22–0.30秒近停及0.44–0.92 mm X拖尾；不是物理即停或完整真机性能验收。

新增[AprilTag 默认相对位姿跟随](../../marker/records/marker_detect.md#tag-follow)：tag10 多姿态 X/Z 标定、LB+305 保存默认关系、LB+304 跟随及异步 RL 集成。当前使用接收时间检查、0.08增益、0.5 mm/0.2°每轴步长与独立死区；已有现场采样、独立跟随试用和软件回归，完整闭环精度及训练内现场切换仍待量化验收。[操作教程](../../../../tutorials/marker_detect.md#tag-follow)。

新增[SpacePilot 机械臂增量发送](../../teleoperation/records/hardware/evolution/spacepilot-control.md)：独立平移/旋转 scale、自动手动路由、显式执行及停止处理已实现；离线验证和设备只读连接通过，真机逐轴与操控手感待验收。原 SpacePilot GUI 仍仅操控虚拟物体。

新增[控制接收端迁移](../../control/records/hardware/evolution/robot-controller.md)：原包与363文件哈希校验、本机Jazzy构建、5项断开设备/假IK测试通过。默认不连接，不代表真机闭环验收。

新增[双相机输入选择](../../policy/records/training/evolution/eef-action-space.md#v2可选腕部相机与输入源标记)：
腕部与外部各3×128×128，显式camera_mask及off/required/optional配置；
双相机、关闭、整路腕部缺失均实际两轮140条影子候选通过；最新完整测试155 passed、6 skipped。

新增[末端6D动作实验](../../policy/records/training/evolution/eef-action-space.md)：bag_004共69代理标签，
500步单段BC，140条类型化ROS影子候选实收及载荷核对通过；旧关节BC回归109条。
末端初版测试147 passed、6 skipped，另ROS消息专项10 passed；无真机/泛化验收。

证据等级：**代码/静态**、**自动测试**、**headless 仿真**、**人工 GUI 观察**、**设备只读**、**真机运动**。以下状态仅针对 OMI 当前代码。

| 能力 | 当前入口 | 已验证 | 尚未验证 |
| --- | --- | --- | --- |
| [AprilTag 标定与默认位姿跟随](../../marker/records/marker_detect.md#tag-follow) | `tag_handeye_calibration.py`、`tag_follow_tag_v2.py`、`run_async_rl.sh --tag-follow-calibration ...` | 20样本X/Z通过当前内部门槛；现场独立试用；独立死区、恢复及延迟模型等83项相关回归 | 新参数真实闭环精度/长期稳定性；训练内完整切换现场验收 |
| [SpacePilot 六自由度物体位姿](../../teleoperation/records/hardware/evolution/spacepilot-pose.md) | `bash scripts/spacepilot_pose.sh` | 项目内 6 项自动测试、设备只读连接；GUI 状态见编年 | 最终 roll 手感、实体键逐键人工验收、机器人/ROS/RL 接入 |
| 独立手柄纯录包与实际指令审阅 | `record_demo_bag.sh`、`training.passive_audit`、`training.passive_preview`、`view_demo_dataset.sh`；[教程](../../../../tutorials/demo_bag_dataset.md) | 用户四包只读审计、335条严格观测/实际wire配对、双指wrench历史、PNG/HTTP及键盘页面部署 | 成功/返回段标注、accepted-command证据、真实BC效果；wrench网络接入 |
| Stand方向修正版录包可视化 | `scripts/view_corrected_stand_observation_3d.sh` | 新旧链随机角度数学对照、单元测试、RViz启动及截图；派生模型命名归档 | 真机base/TCP及限位；左joint4限位已知不一致，不可控制 |
| A 臂 MJCF 加载和任务预检 | `python -m omi_hil_rl.sim.preflight --scene ...` | 外部场景在本机加载；headless 仿真与自动测试 | 现场模型、工具和 TCP 一致性 |
| A 臂末端到达任务 | `TianjiAReachEnv` | 目标可达；策略独立评估 30/30（固定简单目标） | 真实设备、视觉变化和扰动 |
| 代理模型接口测试 | `TianjiSurrogateEnv`、`sim.smoke` | 自动测试 | 代理动力学代表性 |
| 键盘逐关节点动与 JSONL | `sim.keyboard_teleop` | 解析和记录接口自动测试；脚本示范实际运行 | 人工键盘操作的现场体验、连续遥操作 |
| 策略运行中键盘接管 | `sim.interactive_rollout` | 2 步命令行回归：1 条人类、1 条策略 transition；校验通过 | 连续低延迟接管 |
| 脚本接管与动作仲裁 | `ScriptedInterventionWrapper`、环境 `step` | 自动测试；headless 训练 | 真人在线接管延迟 |
| 奖励与回合结束 | 环境 progress/sparse 模式 | 训练进度奖励；独立评估稀疏成功奖励；TCP 阈值和超时已在仿真运行 | 视觉奖励、真机任务奖励、碰撞/力惩罚 |
| SAC 训练、HIL 双流回放、示范导入 | `training.sim_train` | 1500 步仿真训练；7 条离线示范导入；双流采样和环形覆盖测试 | LeRobot actor/learner、真机在线训练 |
| 原生录包BC与ROS影子推理 | `scripts/bag_bc.sh`，见[教程](../../../../tutorials/bag_bc_shadow.md) | 108样本500步实际训练，两轮ROS接收218次预测，输入精确一致、无控制topic | 独立episode泛化、动作物理语义、真设备/控制、既有SAC初始化集成 |
| 磁盘回放、预取与恢复 | `DiskHILReplayBuffer`、`--replay-backend disk` | 图像/状态自动测试；A 臂 200 步；缓存 batch 基准 | 超内存冷盘性能、长时采集、真机时限 |
| Policy improvement 审计 | `policy_progress.jsonl`、`training.plot_progress` | SAC+BC 0/10 → 10/10；低熵纯 SAC 0/10 → 10/10，另取 30 回合 30/30；默认熵纯 SAC 对照失败 | 原版分布式实现与跨目标泛化 |
| 录制格式校验与独立评估 | `validate_recording`、`sim_eval` | 1500 条记录校验；30 回合评估 | 长期统计泛化 |
| MuJoCo 离屏可视化 | `sim.visualize` | EGL 离屏渲染；PNG/GIF 已生成 | MuJoCo GUI/Viewer 人工观察 |
| 真机 ROS 多模态只读观测 | `real.ros_bag_preflight`、`real.ros_observation_live` | `record010` 产生 269 个有效 observation；专项测试 8 passed | 在线 ROS 图、真机时延与策略集成 |
| 相机 ROI/RViz 辅助显示 | `../ros2_camera_clip_tools/view_camera_clip*.sh` | 原图/128、独立 512 与双进程模式；用户人工观察 | 真机在线相机、端到端延迟与长期性能 |
| Tianji SDK A/B 适配 | `TianjiSdkArm` | 假 SDK、MuJoCo SDK 替身自动测试 | 设备只读连接、真机运动、故障现场验收 |

新增[触觉实时回放](../../sensors/records/hardware/evolution/tactile-live.md)：原始 bag 重建双指向量数值，
独立 dashboard 约 10 Hz 实收；RViz GUI 交互、真机在线和完整触觉验收仍待完成。

新增同一播放器的[相机与触觉合并显示](../../sensors/records/hardware/evolution/tactile-live.md#相机与触觉合并模式)，
原图/128 ROI 与双指向量同屏，实收约 9.94 Hz。

相机触觉合并显示阶段为 **59 passed, 1 skipped**；最新测试见本页顶部，前阶段数字保留在历史编年记录。
四项训练机制见 [训练纪传体](../../simulation/records/training/evolution/hil-training.md)，磁盘验证见
[开发编年](../../replay/records/training/chronicles/2026-10-02-disk-replay.md)，完整对照见
[HIL RL 审计](../../simulation/records/hil_rl_reproduction.md)。SDK 适配器默认无运动授权。
