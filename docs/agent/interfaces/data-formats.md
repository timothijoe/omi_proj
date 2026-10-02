# 数据格式与单位

新增回放触觉数值契约：带源 header 的 `32FC2` deformation/shear、配对 raw、带基准哈希
和身份的 JSON metadata。详见[实时触觉显示](../hardware/evolution/tactile-live.md#数据契约)。
此契约尚未并入策略 observation 或 replay。

## 环境契约

动作是 `float32[7]`，每轴归一化范围 `[-1,1]`，代表相对于当前关节角的增量；在当前仿真每轴满量程为 `0.04 rad`。观测字典含 `state: float32[14]`（前七关节角 `rad`，后七关节速度 `rad/s`）、`tcp_pos: float32[3]` 和 `target_tcp_pos: float32[3]`（世界坐标 `m`），共 20 个数值。`terminated` 表示任务成功，`truncated` 表示步数上限。训练 progress 与评估 sparse 奖励的定义见 [训练纪传体](../training/evolution/hil-training.md#2-奖励与回合结束)。

`info` 至少包含 `policy_action`、可选 `human_action`、`executed_action`、`action_source`、`commanded_joint_target_rad`、`tcp_error_m`、`model_kind` 和 `task`。此处 `executed_action` 是经过仲裁和限位的**命令增量**，不是经真实设备反馈确认的实际运动。

`action_source` 目前只有 `policy` / `human`，其中 `human` 包括脚本教师和真人输入。教师身份、输入设备和奖励模式没有独立字段；仅凭 JSONL 的来源标签无法证明真人干预。代理任务与 A 臂任务的奖励距离单位不同，不能混用。

## JSONL

`TransitionRecorder` 每步写一行 JSON：`episode`、`step`、`observation`、`policy_action`、`human_action`、`executed_action`、`commanded_joint_target_rad`、`action_source`、`reward`、`next_observation`、`terminated`、`truncated`、`model_kind`、`task`、`tcp_error_m`。`validate_recording` 检查动作来源、形状、有限值和同回合观测连续性；它不判定示范质量或物理安全。当前格式**没有 schema_version、绝对时间戳、设备帧号、策略版本或真实动作确认**，实机使用前应升级并迁移数据。

## Replay 内部契约

`HILReplayBuffer` 保存字典观测和下一观测、归一化最终命令动作、奖励、done、timeout，以及 `human_mask` / `online_mask`。`done=terminated or truncated`；SB3 通过超时标记使时间上限截断的样本仍可估计后续价值。

写入接口的 `info.action_source` 必须是 `human` 或 `policy`。`replay_origin` 默认 `online`；导入示范使用 `offline_demo`，且必须为 `human`。`replay_origin` 是入池路由字段，不是现有 JSONL 字段。入池后不保留整份 `info`，动作审计在 JSONL。

`stream_counts()` 输出 `online`、`demonstration`、`offline_demonstration`；在线干预是前两者的交集，第三者是示范流中不属于在线流的部分。`replay.pkl` 保存池及标记，是训练快照，不是可直接驱动真机的轨迹，也没有对应的 CLI 续训入口。容量、抽样和覆盖行为见 [Buffer 纪传体](../training/evolution/hil-training.md#4-buffer-的存储与采样)。

## 磁盘 Replay

磁盘后端使用 schema_version=1 的 `manifest.json` 和 `.npy` 数组，元数据含 shape/dtype、容量、ring 位置、full、采样比例与 clean 标志。由 `DiskHILReplayBuffer.checkpoint/reopen` 保存/恢复，不生成 `replay.pkl`；dirty checkpoint 拒绝重开。字段、锁与保存边界见 [磁盘经验池](../training/evolution/disk-replay.md)。

## SDK

厂商 SDK 关节目标和反馈使用**度**，`TianjiSdkArm` 对外使用**弧度**。`TianjiArmState` 包含七关节角、反馈帧号、控制状态、错误码和单调时钟接收时间。仿真 MJCF 关节角为弧度；两者不能直接混用。

## 触觉零载荷基准包

`omi_hil_rl.real.tactile_baseline` 在一个新目录中生成 schema version 1 的离线基准包：

- `tactile_a_base.npy` / `tactile_b_base.npy`：原始分辨率的 `uint8 H×W` 时间中位数；
- `tactile_baseline.npz`：两张基准及参与聚合的 bag 时间戳；
- 两张同名 PNG：仅供人工查看；
- `open_gripper_contact_sheet.png`：窗口内五个固定时刻的外部相机画面；
- `metadata.json`：bag、相对时间窗口、topic、帧数、shape/dtype、raw 稳定性、零载荷检查、
  serial 映射与限制。

当前零载荷检查阈值是针对录包验证的启发式条件：夹爪位置最小值不低于 0.95，双侧平均
合力模长不高于 1.0，双侧平均 depth 不高于 0.02。由于厂商力单位尚未确认，这些阈值
不是物理校准限值。生成器拒绝覆盖已有输出目录；基准包位于 `local/`，不进入 Git。

## 触觉离线场探针

`tactile_offline` 每个逻辑侧和目标时刻生成压缩 NPZ：raw、`288×384×2 float32`
deformation、同 shape shear、重建 depth、bag 记录 depth 和记录 wrench。PNG 只供人工
查看；`metadata.json` 保存实际选中时间、数值范围、renderer 参数及 depth 对照指标。
当前固定显示参数为 step 16、2 px/unit、deadband 0.2、最大 24 px，禁止逐帧归一化。
重建矩阵没有已确认物理单位；记录 depth 始终保留为独立真值字段。

字段语义如下：

- `a_*` 属于右侧夹爪 A / `X26040546`，`b_*` 属于左侧夹爪 B / `X26040345`；
- `deformation[y,x] = [dx,dy]` 是当前触觉纹理相对零载荷基准的二维稠密位移；
- `shear` 是厂商 `Decomposer` 从 deformation 派生的同 shape 二维场，厂商示例称为
  `2D curl`，当前只解释为剪切、旋转和滑移相关特征；
- renderer 按图像坐标把 `+x` 画向右、`+y` 画向下，但左右图像坐标尚未标定到统一的
  夹爪/机器人坐标系；
- deformation、shear 都不是标定后的力，箭头长度不能解释为 N，shear 也不能直接解释为
  已标定切向力。
