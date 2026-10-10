# 2026-10-10：单帧 BC 录制到 Learner 的离线验证

## 结论

用户要求实际验证：Learner能否从本批单帧记录重建十帧历史observation，并使用这些输入训练。
离线验证已通过。19回合导出3579条transition、38个训练片段；真实多模态SAC在CUDA上完成
8次Critic更新和3次Actor更新，检查点恢复与Actor重载输出一致。
更新只发生在独立验证目录，原始BC12045、录制数据和正式RL目录没有被更新。

## 来源与产物

- 原始来源：`local/bc_episodes/demo_new_20261007_213643_eval_01/`，固定BC12045录制的19个单帧格式回合。
- 验证目录：`local/diagnostics/bc12045_learner_validation_20261010_02/`。
- `validate.py`：本次独立验证脚本；重新执行须复制到新的目录，拒绝覆盖已有 `run/`。
- `validation.log`：逐回合转换、Learner阶段与最终通过日志。
- `report.json`：完整结果；`conversion_report.json`、`training_report.json` 分别保存转换和训练证据。
- `source_hashes.json`：原会话11257个文件的SHA-256；`observation_digests.json` 保存窗口内容摘要。
- `run/periodic_episodes/`：验证副本；`run/episodes/`：派生的ready/imported片段。
- `run/replay/`、`run/learner.pt`、`run/actor.pt`：仅供本次验证的经验池和更新权重。
- `run/validation_only.json`：记录验证配置差异。该目录没有正式async session启动标记。

成功运行总耗时326.82秒，产物文件长度合计1,691,635,175字节，包含派生数据、固定容量验证replay
和模型。这个大小不属于原始BC录制目录的占用；没有把正式replay改成单帧格式。
初次 `_01` 诊断脚本在汇总重复的 `episode` 关键字时报错，修正诊断脚本后在新 `_02` 完整重跑。
`_01` 不计成功验证，未在其中运行Learner；本次未修改生产训练代码。

## 重建、转换与标签

采用生产代码 `ObservationReader` → `PeriodicAudit(training=True)` → `periodic_replay.convert`
→ `EpisodeSpool/read_episode`，逐条回放已录制的观测、实际动作、回执、干预时间和结束边界。
来源会话持有Actor目录锁，整个过程不连接ROS、机器人SDK或手柄，不创建动作发布者。

| 检查项目 | 结果 |
| --- | ---: |
| 原始回合 | 19 |
| 独立观测节拍 | 3672 |
| 有效观测／明确缺失记录 | 3663／9 |
| 已发送动作记录 | 3617 |
| 核对窗口总数（观测＋动作＋结束边界） | 7308 |
| 可导出的transition | 3579 |
| 人工来源／BC策略来源 | 2273／1306 |
| 排除记录 | 38条握手零动作，`no_action_candidate` |
| 连续训练片段 | 38 |
| 保留的成功奖励 | 8 |
| 当前有效但历史不满十帧的transition | 9 |

帧文件内容哈希、字段shape/dtype、有限值均核对；验证副本7308个窗口的内容摘要与来源重建窗口一致。
3579条transition的observation和next_observation逐字段、逐字节与对应原始动作输入/结束边界一致；
执行动作、human/policy来源也逐条核对。缺失节拍仍是缺失记录，零占位与mask保留，未补造EEF。

这是按已保存帧引用重建并验证派生链路，不声称拿到了当时已经退出进程的内存快照作比较。
保留 `timing_policy=diagnostic_only_v1`；时序告警依照现行契约只作诊断，未新增入池规则。
成功奖励沿用操作者按键标签，不作为独立核验任务成功的证据。

## 实际 GPU 训练与恢复

使用 `hil.learner.run_learner`、真实 `current9stack` 多模态编码器和原始BC12045参数初始化SAC。
GPU为NVIDIA GeForce RTX 5060 Laptop GPU；batch=2，冻结编码器，Actor学习率1e-5，人工BC约束权重10。

为在短验证中同时覆盖预热和Actor更新，**仅验证副本**的Critic预热设为2步，正式配置的1000步未修改。
仅使用本批数据，不额外导入此前1387条初始示范；人工示范流由本批人工干预提供。

| 阶段 | 累计Critic更新 | 本阶段Actor更新 | 阶段末Critic loss | 阶段末BC loss |
| --- | ---: | ---: | ---: | ---: |
| 预热 | 2 | 0 | 1.084040 | — |
| SAC＋BC | 6 | 2 | 0.346707 | 0.372715 |
| 再次恢复继续训练 | 8 | 1 | 0.148872 | 0.177446 |

以上损失来自不同抽样batch，只证明有限值与更新链路，不是学习改善或收敛曲线。
预热后Actor参数逐项不变；最终Actor头最大参数变化约3.0050e-5，Critic头约0.00226119。
编码器及固定BC参考参数均逐项不变。模型参数与损失有限，checkpoint恢复后从6继续到8，没有重新初始化。
最终 `learner.pt` 恢复出的Actor与发布的 `actor.pt` 对同一真实窗口输出逐元素一致，最大差0。
PyTorch本进程CUDA峰值allocated约194.3 MiB，不包括桌面或其他进程占用。

## 经验池验证范围

为限制诊断占用，online和interventions各设256条容量，初始示范区为空并封存。
3579条transition全部经过生产校验和导入，38个片段全部写出imported标记。
环形池覆盖后保留online256、interventions256；两者有交集，不能相加当作512次不同经历。
两区全部512个保留槽位的observation/next_observation与对应源记录摘要一致。
后续恢复阶段新增导入数为0，没有重复导入。

实际训练采用这个小池的抽样batch；不代表所有3579条都参与了梯度更新。
本轮验证了全量重建、转换、导入和抽样训练，未执行完整数据集拟合、超参数选择或策略效果评估。

## 收尾状态

Learner有界运行已结束，最后阶段监控为 `CLOSED`；原BC会话仍为 `CLOSED/learner_enabled=false`。
来源11257个文件及原始BC来源权重前后SHA-256一致，原会话仍没有ready片段或replay目录。
验证成功不等于当前BC入口已经自动启用在线训练：派生训练数据和新权重只存在于上述验证副本。

本批现场数据与EEF现象见[现场记录](2026-10-10-fixed-bc-storage-live-review.md)，
存储实现见[单帧存储记录](2026-10-10-observation-frame-storage.md)。
