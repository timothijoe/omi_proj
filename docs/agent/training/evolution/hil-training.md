# HIL 训练与数据流

`training.sim_train` 在 `--scene` 存在时创建 A 臂 TCP 到达环境，否则使用代理关节目标任务。脚本教师前 `--demonstration-steps` 步持续接管，随后按 `--later-intervention-probability` 接管；这是可重复仿真替身，不是人工输入。环境在每步同时报告 `policy_action`、可选 `human_action`、限位后的 `executed_action` 与 `action_source`。`ExecutedActionSAC` 存最终执行动作，`HILReplayBuffer` 默认使批次一部分来自人类/教师样本，`DemoRegularizedSAC` 用这些样本做辅助行为克隆。

`TransitionRecorder` 写 `transitions.jsonl`，`validate_recording` 检查状态维度、动作来源与同回合连续性。`--demo-recording` 先校验 JSONL，再仅把 `action_source=human` 的 transition 放入示范流；要求模型类型和观测空间一致。在线干预同时属于在线流与示范流，离线导入仅属于示范流，环形覆盖会清除旧标记。有两流时每批默认各取一半。`policy.zip`、`replay.pkl`、`metrics.json`、`policy_progress.jsonl`、周期策略快照及 transition 文件写入指定输出目录。`sim_eval` 新建环境并在**无接管**条件下评估。

当前训练用 CPU 版 PyTorch 与 SB3，既不是 LeRobot HIL-SERL 全量移植，也没有真机 actor、相机、奖励分类器。SAC actor/critic/温度更新由 SB3 执行；OMI 的 BC 是附加策略更新。训练入口允许 `--entropy-initial` 调整 SAC 自动温度的初值。固定种子审计显示默认熵纯 SAC 失败，而 `--bc-weight 0 --entropy-initial 0.01` 的纯 SAC 双流设置可改善此任务；组合设置也成功。JSONL 尚无统一 schema_version、硬件时间戳和确认执行的设备反馈。当前结果与条件见 [四项审计](../../../hil_rl_reproduction.md)。
