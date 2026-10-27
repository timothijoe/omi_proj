> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-external-archive-restore.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/replay.md)；本页保留原过程与证据。

# 2026-10-11：外盘归档与真实buffer恢复验证

用户确认训练停止，要求归档checkpoint和数据，并提供恢复接口与buffer教程。
目标：`/media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data/`。

## 停止状态与归档

Actor/Learner均CLOSED、无error或强制终止，actor/learner/replay写锁可获得，SQLite已干净checkpoint。
最终Actor/Learner checkpoint均 **16677**，现场Actor最后加载16150。
索引53513条有效transition：43759策略、9754人工，固定历史seed0。
原始回合140个：成功64、timeout69、人工提前结束5、异常2，全部保存。

外盘为exFAT，采用未压缩tar封装已压缩NPZ，避免大量小文件各占一个大分配单元。
本次是**完整外盘归档副本，本机原目录保留**；未删除源数据或启动机器人。
此前两批另行归档的问题数据不混入本会话；当前会话内部的异常审计仍保留。

| 归档文件 | 内容 |
| --- | --- |
| run.tar | 221646文件，原内容5,782,247,152字节，tar大小6,164,541,440字节 |
| run_files.sha256.jsonl | 会话逐文件大小与SHA-256 |
| checkpoints/actor.pt、learner.pt | 最终16677的便捷取用副本 |
| initial_bc/ | 原BC12045 Actor、config、recipe |
| source.tar及源文件清单 | 681文件、9,416,296内容字节，实际代码/文档快照，含新恢复接口 |
| manifest.json、environment.json | 校验信息、代码状态与环境版本，未打包venv/ROS/厂商SDK |
| archive_tool.py、README.md | 标准库恢复工具及教程 |
| RESTORE_VALIDATION.md、validation/ | 实际从外盘恢复后的说明和buffer/model报告 |

整个包约6.33 GB（5.90 GiB）；逐文件及tar整体SHA、附属模型与报告均校验通过，未完成标记已移除。
代码HEAD为 `e57bd5e04c6db88c76b5d4ea9842f43badd5359a`、分支oct_10_branch；
归档包含新工具等未提交文件，manifest记录工作区状态，不冒充纯HEAD快照。

## 接口与真实恢复验证

新增 `scripts/training_archive.sh` / `hil/run_archive.py`，支持pack、verify、restore、restore-code、probe-buffer。
完整用法见[归档与恢复教程](../../../tutorials/oct11_archive_restore.md)，外盘README也有副本。
接口拒绝活动任务、覆盖已有目标、外部seed/source依赖、非正常tar成员和路径穿越；
工作数据必须解包到本机POSIX文件系统，不直接在exFAT/NTFS上恢复写replay。

实际使用外盘独立工具恢复会话及代码到 `local/diagnostics/oct11_archive_restore_20261011/{run,source}/`，
逐文件校验通过，然后使用解出的代码完成验证：

- 临时1 GiB缓存、2 GiB管线上限：471条独立记录，Demo235、RL299，有共享交集。
- 两池分别抽取batch64；RGB `[64,10,3,128,128]`，触觉 `[64,10,10,16,24]`，数据有效。
- 全量索引仍53513条；管线峰值1,374,695,628字节（约1.28 GiB），加载无错误。
- 原恢复目录的checkpoint、SQLite、manifest哈希不变；临时缓存退出释放，正式16/20 GiB配置未改。
- 完整SAC/优化器可恢复；真实恢复观测上，Actor16677与Learner策略CPU输出逐元素一致且有限。
- 机器人输出0、训练更新0；不保证旧RAM成员、抽样顺序或后续学习轨迹逐位复现。

## 最后449条数据

回合 `96f8e50d35cc48cab2cadf776b802b92` 已结束保存，含449条有效transition，但停止前尚未登记SQLite。
其原始帧、动作、ready片段均已完整打包。probe-buffer按53513条持久化目录验证；
正常Learner续跑会补导入末回合，目录可增至53962条，不是重复导入或丢数据。

23项归档、weights-only及cached replay回归通过，覆盖原目录不可用时的恢复/抽样/续训、
锁保护、防覆盖、损坏tar及路径穿越拒绝。真实恢复证据见本机diagnostics和外盘validation。
用户原任务未重启、训练算法和参数未改。
