# OMI 文档总目录

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
