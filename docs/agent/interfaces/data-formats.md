# 数据格式与单位

## 环境契约

动作是 `float32[7]`，每轴归一化范围 `[-1,1]`，代表相对于当前关节角的增量；在当前仿真每轴满量程为 `0.04 rad`。观测字典含 `state: float32[14]`（前七关节角 `rad`，后七关节速度 `rad/s`）、`tcp_pos: float32[3]` 和 `target_tcp_pos: float32[3]`（世界坐标 `m`）。`terminated` 表示任务成功，`truncated` 表示步数上限。训练 progress 奖励是仿真实验设计，不是设备力学量。

`info` 至少包含 `policy_action`、可选 `human_action`、`executed_action`、`action_source`、`commanded_joint_target_rad`、`tcp_error_m`、`model_kind` 和 `task`。此处 `executed_action` 是经过仲裁和限位的**命令增量**，不是经真实设备反馈确认的实际运动。

## JSONL

`TransitionRecorder` 每步写一行 JSON：`episode`、`step`、`observation`、`policy_action`、`human_action`、`executed_action`、`commanded_joint_target_rad`、`action_source`、`reward`、`next_observation`、`terminated`、`truncated`、`model_kind`、`task`、`tcp_error_m`。`validate_recording` 检查动作来源、形状、有限值和同回合观测连续性；它不判定示范质量或物理安全。当前格式**没有 schema_version、绝对时间戳、设备帧号、策略版本或真实动作确认**，实机使用前应升级并迁移数据。

## SDK

厂商 SDK 关节目标和反馈使用**度**，`TianjiSdkArm` 对外使用**弧度**。`TianjiArmState` 包含七关节角、反馈帧号、控制状态、错误码和单调时钟接收时间。仿真 MJCF 关节角为弧度；两者不能直接混用。
