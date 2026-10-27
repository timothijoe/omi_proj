# 当前数据格式与单位

本页以真机HIL主链为主；版本差异必须以保存的manifest、config和checkpoint核对，不凭文件名推断。实现为 [hil/config.py](../../src/omi_hil_rl/hil/config.py)、[observation_storage.py](../../src/omi_hil_rl/hil/observation_storage.py)、[exchange.py](../../src/omi_hil_rl/hil/exchange.py)。

## 真机观测与动作

`hil-nojoint-current9stack-v1-ros`的单样本字段（不含batch维）：

| 字段 | shape / dtype | 含义 |
| --- | --- | --- |
| rgb / wrist_rgb | 各(10,3,128,128) uint8 | 外部/腕部，按旧到新十槽 |
| tactile | (10,10,16,24) float32 | 每指deformation两通道、shear两通道、depth一通道 |
| state | (10,14) float32 | 关节占位7维+EEF xyz/xyzw7维；当前无关节模型忽略前7维 |
| camera_mask | (10,2) float32 | 外部/腕部可用性 |
| history_mask | (10,) uint8 | 实际历史槽是否有效 |
| action | (6,) float32 | 每分量[-1,1]，六维末端命令 |

物理动作等于归一化分量乘会话的 `physical_action_scale`，前三项米、后三项弧度旋转向量。尺度、腕部off/optional/required、EEF参考、10Hz和回合时限都属于契约。SpacePilot新数据不得按旧手柄尺度解释。wrench_history是显式可选扩展，并非上述基本契约必含。

`action_semantics=accepted_command`：标签是仲裁及接受后命令，不是实际位移。SDK wire为mm/ABC度；实际反馈与命令严格分开。`no_gripper=true`表示动作空间不含夹爪，不意味着人工夹爪按钮被关闭。

reward_contract为人工成功0/1、超时bootstrap。成功末条terminated；超时和普通结束truncated。异常回合及缺失/拒绝命令按审计排除。来源human/policy不能单独证明自主成功。

## periodic记录与帧库

`observation_storage_version=omi-observation-frames-v1`。元数据的 `observation_storage.observation`/`next_observation`含version、相对directory与按旧到新排列的十个SHA256帧ID。原始帧存于 `periodic_episodes/<episode>/frames/<id>.npz`，按字段名、dtype、shape及原始字节计算哈希，读取时校验并stack恢复。

observations按实际reference_ns保存，动作携带实际输入快照，末步用边界观测；历史不按动作数量倒推。旧内嵌数组仍可读，同字段同时内嵌与引用则拒绝。ready片段依赖原回合帧库，归档不可遗漏。

`timing_policy=diagnostic_only_v1`的普通periodic数据将时序迟到保存为诊断，不照搬旧严格配对门槛。SpacePilot `manual_timing`额外记录actual_command_interval_s，要求观测递增、间隔80–150ms且无外部停止，不合格仅审计分段。旧记录没有新标志时保留原规则，不伪造新时间戳。

当前latest缓存路径可能在断流后继续提供同一旧RGB且camera_mask仍为1；因此mask代表现有输入可用性，
不能宣称它已经实现基于接收年龄的新鲜度门控。10月24日事故已确认该缺口，见[传感器模块](../modules/sensors.md)。

## 删除回合台账

run根目录的`episode_removals.json`使用`schema=omi-episode-removals-v1`和`started_episode_ids`字符串列表。
累计回合预算对现有原始ID与该列表取并集；恢复同名目录不会重复计数，删除不会返还名额。
缺失台账沿用目录计数；未知schema、重复或非法ID拒绝使用。台账不存可训练帧，不改变权重或撤销梯度更新。
实现见[async_training.py](../../src/omi_hil_rl/hil/async_training.py)，清理过程见[经验池模块](../modules/replay.md)。

## cached索引与来源

`manifest.json.backend=omi-cached-dual-replay-v1`保存完整contract及预算；`catalog.sqlite3`保存sources指纹、records来源定位/时间/动作/奖励/归属。完整来源校验后一次事务登记，RAM数组不是恢复真值。

seed只属Demo，online human同时属Demo/RL，policy只属RL。`stream_counts`表示驻留可采样成员，`catalog_*`表示全量登记，交集不可重复相加。imported标记的catalog_registered不保证resident。外部来源路径需要保留，移动来源不能只改一个文件名。

## 其他契约边界

旧bag-bc-v1为7关节目标假设，bag-eef-bc系列为未来EEF变化代理标签；不得混入accepted-command主链。仿真为7维关节增量、单步0.04rad，观测为关节角/速度及TCP/目标；SDK关节角单位度，适配与仿真对外弧度。

触觉数值和可视化图区分见 [术语](../../CONTEXT.md)；不把deformation/shear当标定力，不逐帧min-max制造固定幅值。源header、接收时间与设备fid缺失时保留未知，不补造同步证据。

历史格式细节仅在复现时查 [归档索引](../archive/cross-cutting/README.md)；当前机制见 [replay](../modules/replay.md) 和 [policy](../modules/policy.md)。
