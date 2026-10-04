# 在线历史 policy 与可选 wrench

> **实机对接暂定约定：** 用户指定暂按基坐标系旋转向量解释控制接口后三维，尚未经接收端核实。策略输出仍为m/rad，axis_test接口为mm/度；单位换算不能替代基坐标系和TCP变换。具体公式与条件见[动作接口对齐说明](axis-controller-interface.md)。

## 当前实现

2026-10-04：新增在线历史推理接口，复用 `HistoryPolicy` 编码器、GRU 和归一化。
当前可用旧 v3 历史权重做影子推理；新增 v4 数据与模型接口支持可选 wrench。
v4 尚未训练。本轮没有启动新训练，也没有接机械臂执行器。

代码入口：

- `src/omi_hil_rl/training/eef_history_online.py`：纯 Python `OnlineHistoryPolicy`。
- `src/omi_hil_rl/training/eef_history_node.py`：ROS 接收、定时推理和候选发布。
- `src/omi_hil_rl/training/eef_bc_wrench.py`：wrench 数据契约、有效性判断与缓冲。
- `src/omi_hil_rl/training/eef_bc_data.py`：v4 导出。
- [操作教程](../../../../tutorials/eef_history_online.md)。

## 历史如何进入在线推理

每 100 ms 取一次观测，窗口是 `[t-0.9s, ..., t]`，共 10 个固定时刻。
每个时刻分别对齐最新且不晚于该时刻的数据；时间轴使用本机接收时间。
EEF 最大数据年龄 50 ms，其他输入 250 ms；header 超前接收时间超过 100 ms，
或落后超过对应年龄阈值则不采纳。跨机器时钟偏差仍需要在部署前核实。

每个有效时刻编码为 128 维特征，只缓存最近十个槽位内的特征。
缺帧保留对应 mask=0，不把前面的帧挤到缺口里。每次预测从零初始化 GRU hidden，
重算该窗口；它不是无限积累状态的 RNN。相机 mask、历史 mask、wrench mask 各司其职。

当前必需输入缺失时不发布动作；可选腕部图像缺失时置零并设 camera_mask=[1,0]。
输入时间回退、显式 reset、wrench 开关改变会清空源数据和历史并递增 epoch。
切换 episode 或录包循环必须 reset；程序无法凭正常递增的时钟推断操作任务已经切换。
调度迟到时跳过错过的时刻，推理结束已超出该帧 100 ms 有效期则丢弃候选。

### Python 接口

```python
runtime = OnlineHistoryPolicy(checkpoint, wrench_enabled=(0, 0))
runtime.ingest(key, ros_message, receive_ns, source_valid=True)
status = runtime.step(reference_ns)  # 固定 100 ms 网格
runtime.set_wrench_enabled((0, 0))  # 变化时 reset
runtime.reset()                    # 新 episode
```

这些方法要求单线程调用；ROS 入口使用单线程 executor。
`push(reference_ns, aligned_observation)` 用于已经对齐的观测和离线验证，调用方负责输入的新鲜度；
直接接收 ROS 消息应使用 `ingest/step`。重复或回退的 `push` 时间必须先 reset。

## wrench 数值与 label

双指 wrench 单独保存，不改变原 state14（左臂 q7 + EEF pose7）。

| 字段 | 单帧维度 | 语义 |
| --- | --- | --- |
| `wrench` | float32[12] | A 指 Fx,Fy,Fz,Tx,Ty,Tz，再 B 指六维 |
| `wrench_enabled` | float32[2] | 数据集/运行配置，是否允许该指 wrench 生效 |
| `wrench_mask` | float32[2] | 本帧该指 wrench 是否实际有效 |
| `camera_mask` | float32[2] | 外部相机、腕部相机是否可用 |
| `history_mask` | bool[10] | 十个历史时刻是否有有效输入 |

`wrench_mask = enabled AND 数据存在 AND 数值有限 AND 时间有效 AND source_valid`。
禁用、缺失、过期、NaN/Inf 或显式 source_valid=False 时，对应六维全部置零。
即使原始 bag 有非零 wrench，也可以通过 enabled=0 禁用。
真实测量为零且其他条件满足时，mask=1；因此模型可以区分“测得零”和“没有可用测量”。

启用配置允许按录包不同，兼容格式可以混合。模型接收 wrench12 + mask2；enabled 用于生成
mask 和审计，不额外占模型输入维度。训练只用训练集有效 wrench 估计逐维 mean/std；
无有效值的指采用 mean=0、std=1。归一化后再次屏蔽，使无效值在模型输入处仍为严格零。
训练及推理都会检查 mask<=enabled 和无效数值为零。

这里“有效”表示数值可用，不表示物理力已经标定。当前 SDK 的单位、轴向和与触觉场
同帧关系仍未确认。ROS WrenchStamped 本身没有有效位，ROS 入口检查数值与时间；
需要外部质量标签的接入方可以调用 `ingest(..., source_valid=False)`。
当前 ROS 入口没有另接厂商质量 metadata topic。

## 新旧训练格式与在线一致性

- v3 权重没有 wrench 输入。在线设置 enabled=[0,0] 可用；尝试启用 wrench 会报错，不能直接追加维度。
- v4：`bag-eef-bc-v4-wrench`，固定保留 wrench12、mask2、enabled2，需重新训练对应权重。
- 外部 RGB、腕部 RGB 都保持 `[3,128,128]`，触觉 `[10,16,24]`，state `[14]`，动作 `[6]`。
- v4 `samples.npz` 保存有动作标签的样本；`history_observations.npz` 保存所有有效因果输入，
  包括没有合格未来标签的时刻。manifest 保存两个文件的 SHA256。历史训练按 target 的时间
  索引完整观测池，避免未来标签是否可用反过来决定历史帧是否存在。
- v3 历史训练只用了最终保留的带标签样本。旧权重在线应用于全部有效观测存在输入分布差异；
  当前数值一致性验证限定为“同一组保留观测”，不能解释为原始流严格等价。
- 通用旧 `bc_shadow` 仍拒绝 v3/v4，因为它使用另一套时钟约定。这里使用独立在线入口。

## 输出契约

候选 `/omi/history_shadow/action_delta`：`std_msgs/Float64MultiArray`，六维
`[dx,dy,dz,rx,ry,rz]`。前三维为 base_link 下米，后三维为基坐标轴下旋转向量，单位 rad，
按 `Exp(rotation) * R_current` 左乘；不是欧拉角，也不是速度。
layout.dim[0].label 包含 epoch、sequence、reference_ns、expires_ns 供候选与状态关联。
有效期为 reference+100 ms。拒绝非有限动作、平移范数>0.05 m 或旋转范数>0.25 rad。
这些是实验拒绝阈值，不是机械臂安全控制器。

`/omi/history_shadow/status` 为 JSON String，包含 valid、reason、action、时刻、epoch、sequence、
历史 mask、相机 mask、wrench enabled/mask、源时间和推理耗时。正常 v4 流还提供 wrench_reasons。
当前必需输入无效时 action=null，只发布状态。下游不能把最近一次候选当作持续控制指令。
Float64MultiArray 无标准 header；接执行器前需要明确校验有效期与状态的适配层，目前未实现。

## 已验证与限制

- 旧 best.pt、bag_004/008 共 242 样本：逐帧在线与批量离线最大绝对差 `1.1641532182693481e-9`。
- 真实 bag_001 v4 导出：126 个动作标签、127 个有效历史观测；enabled=[0,0]，wrench 和 mask 全零。
- ROS localhost domain97 合成输入：59 帧候选实收，完整历史出现，停输入后停止动作发布；
  有效帧最大推理时间 2.658164 ms，仅代表此次本机测试。
- 单元测试覆盖缺口、reset、配置变化、无效 wrench、归一化屏蔽、新历史池和旧权重兼容。
- 未训练 v4、未验证带实际有效 wrench 的任务收益、未验证跨机器 ROS/真机执行。
- 测试产物：`local/eef_history/oct04_interface/`；数据：`local/datasets/oct04_wrench_interface/bag_001/`。

阶段记录见 [2026-10-04 编年](../chronicles/2026-10-04-history-online-wrench.md)。
