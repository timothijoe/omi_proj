# Python 模块与边界

| 边界 | 入口 | 输入与输出 | 状态 |
| --- | --- | --- | --- |
| A 臂 MuJoCo 任务 | `sim.tianji_a_reach.TianjiAReachEnv(scene=...)` | Gymnasium `reset/step`；七维归一化动作、字典观测 | 仿真已运行 |
| 快速测试夹具 | `sim.tianji_surrogate.TianjiSurrogateEnv` | 同一动作来源字段；默认关节目标任务 | 自动测试 |
| 脚本接管 | `sim.intervention.ScriptedInterventionWrapper` | 策略动作、概率、教师动作 | 仿真已运行 |
| 交互接管 | `sim.interactive_rollout` | 策略建议 + 终端键盘覆盖 → 环境步骤 | 两步命令行回归 |
| 逐步录制 | `training.recording.TransitionRecorder` | Gym 环境 → JSONL | 自动测试与仿真已运行 |
| 示范导入 | `training.demo_import.import_human_demonstrations` | JSONL → HIL 回放 | 合成录制短跑 |
| SAC 与经验池 | `DemoRegularizedSAC`、`HILReplayBuffer` | 执行动作与来源 → 更新 | 仿真已运行 |
| 磁盘经验池 | `training.disk_replay.DiskHILReplayBuffer` | Dict[Box] → memmap；sample/checkpoint/reopen/close | 图像自动测试、A 臂短跑 |
| 改善曲线 | `training.plot_progress` | 周期评估 JSONL → PNG | 图已生成 |
| Tianji SDK | `hardware.tianji_sdk.TianjiSdkArm` | SDK 反馈/目标，度↔弧度 | 假 SDK 测试；未连真机 |
| 触觉零载荷基准 | `real.tactile_baseline` | rosbag 无接触窗口 → A/B 中位数 raw、预览与 JSON | `record010` 实际提取通过 |
| 触觉向量显示 | `real.tactile_vectors.render_vector_field` | 浮点 `H×W×2` → 固定参数 RGB 箭头与统计 | 合成方向自动测试；未接真实矩阵 |
| 触觉离线重建 | `real.tactile_offline.probe_bag` | raw+base+厂商 CPU 算法 → deformation/shear/depth | `record010` 三时刻实际运行；不连接设备 |

`TianjiAReachEnv.step` 支持策略动作，以及 `intervention_active=True, human_action=...` 的人工覆盖；环境先限位再执行，并返回实际命令增量。内部环境和训练类目前服务单进程仿真，不承诺稳定外部包 API。硬件适配器只能在独立现场验收后进入真实 actor。

训练的干预时序、奖励、SAC/BC 更新和经验池接口详见 [HIL 训练纪传体](../training/evolution/hil-training.md)。`sim.interactive_rollout` 只推理和录制，`training.sim_train` 才更新策略；脚本教师和真人动作目前共享 `human` 来源标签。
