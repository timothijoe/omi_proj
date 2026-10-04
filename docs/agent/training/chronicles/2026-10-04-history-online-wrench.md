# 2026-10-04：在线历史推理与 wrench 有效性标签

## 目标与实现

将此前 10 槽位 GRU 历史机制接入在线影子推理，并允许有 wrench 的录包按配置禁用该输入。

新增 `OnlineHistoryPolicy`、ROS 节点和 `scripts/eef_history_online.sh`。
在线按接收时间对齐，10 Hz 推理，缓存最近十槽特征；缺帧保留 mask，reset/时钟回退/开关变化
清空历史。Float64MultiArray 发布六维候选，JSON 状态给出序号、有效期与各类 mask。
输入无效或推理超时不发布动作。默认 localhost domain97。

新增 v4 契约，固定 wrench12、wrench_enabled2、wrench_mask2。
禁用/缺失/过期/非有限/显式无效时对应六维为零，归一化后再次屏蔽。
旧 v3 权重仍走原维度，仅允许 wrench_enabled=[0,0]。

发现 v3 训练历史仅包含有标签的保留观测，在线无法利用未来标签决定是否保存历史。
v4 导出增加独立的全量有效观测池，训练目标索引该池，使取历史不依赖未来标签是否有效。
本轮未训练 v4，原实验和权重保留。

## 验证证据

- 相关测试：45 passed、1 skipped。覆盖旧接口、新 v4 模型输入、严格缺帧槽位、reset、
  开关清历史、非有限 wrench、真实零测量、过期输入和归一化屏蔽。
- 当前 best.pt，bag_004/008 共 242 个保留样本逐帧推理，和批量离线输出最大绝对差
  `1.1641532182693481e-9`。范围为同一保留观测序列。
- 从正式 bag_001.zip 实际导出 v4：126 个有标签样本、127 个历史输入；两个开关全零，
  wrench 数值和 mask 全零；load_history 校验、哈希检查通过。
- ROS 合成输入发布/订阅：localhost domain97，实收59帧六维候选；观察到完整十槽历史；
  停止输入后无效状态出现，停止发布动作；有效帧推理耗时最高2.658164 ms。
- Shell 语法和 `git diff --check` 通过。

证据位于 `local/eef_history/oct04_interface/`，导出数据位于
`local/datasets/oct04_wrench_interface/bag_001/`，均为忽略的本地资源。

## 当时限制

v4 未重训；没有实际有效 wrench 的任务评估。wrench 有效位不代表物理单位/轴向标定。
旧权重与原始在线流之间仍有保留样本分布差异。未进行跨机器 ROS 验证或真机控制。
没有连接 SDK 或机械臂执行器，没有 commit/push。

最新机制见[纪传体](../evolution/history-online-policy.md)，操作见[教程](../../../../tutorials/eef_history_online.md)。
