# 经验池、录制与恢复

职责：保存真实动作和观测的对应关系，提供Demo/RL分流采样，并让完整会话可恢复。入口为 [cached_replay.py](../../src/omi_hil_rl/training/cached_replay.py)、[replay_sources.py](../../src/omi_hil_rl/training/replay_sources.py)、[observation_storage.py](../../src/omi_hil_rl/hil/observation_storage.py)。

## 原始数据与单帧存储

periodic回合在 `periodic_episodes/` 保存观测、命令、回执、边界和audit；可训练片段在 `episodes/` 发布ready。单帧按内容SHA256保存，观测文件引用十个有序帧；读取重建完整窗口，不能用“最近十条动作”代替历史。

首窗口保存实际十帧，后续通常只增加新帧；缺失槽保留原mask，不跨回合伪造。旧内嵌数组格式仍支持。归档必须保留片段和原回合帧库，单拷ready目录不完整。

ready表示可供导入；cached的imported表示已登记，不保证当前驻留。完整来源校验后SQLite事务提交；后台只读完整audit，来源指纹防止同ID替换。详细字段见 [数据格式](../interfaces/data-formats.md)。

## 共享双池

| 数据来源 | Demo成员 | RL成员 |
| --- | --- | --- |
| 显式导入的初始示范 | 是 | 否 |
| 在线人工接管 | 是 | 是 |
| 在线策略 | 否 | 是 |

人工交集只保存一份物理数据。当前weights-only基线没有初始seed。正常SAC批次两流各半、独立有放回抽样；这不等于人工/策略各半，同一人工样本可从两流抽中。BC附加项只取Demo。

工作集按近期与随机历史子集刷新，两个流独立选择成员；只有两边都不再需要才释放底层条目。不能把RAM采样视为全历史均匀抽样。当前预算16 GiB驻留目标、20 GiB受管数据管线限制，不是磁盘上限、总RSS或显存限制。

SQLite登记全量索引，原始数据留盘；RAM淘汰不删历史。启动门槛需要两流各自满足，缺少新人工数据时等待。恢复从索引重新填充工作集，成员和随机次序不保证逐位一致。

## 恢复与兼容

### 旧图清理与累计预算

10月24日旧任务因外部相机断流沿用缓存RGB，20个回合／30个派生片段／5681条经验已归档核验后从活动目录与索引删除。
旧任务当时库存51675→45994，权重30897未回滚；清理数据不撤销模型学习影响。后续新任务的初始化与库存另行判断，见[项目摘要](../current.md)。
`episode_removals.json`保存已删除原始回合ID，`remaining_episode_budget`按现有与删除ID的并集计数，避免返还累计300回合名额。
旧任务清理时仍消耗230、剩余70；该数字不适用于后续新run。台账不是可训练数据，不能代替全部原始审计。
备份位于训练扫描范围外，含被删数据和清理前索引／权重，但不含所有保留回合，不是完整任务备份。
当前`latest + diagnostic_only_v1`仍没有全面拒绝过期缓存输入，清理不是长期门控修复。
证据见[断流清理包](../evidence/external_camera_outage_20261024/README.md)，待办见[新鲜度与监控设计](../design/system-health-monitoring.md)。

正常停止后同一run自动恢复，不重新prepare。完整备份必须包含原始帧、索引、checkpoint及外部引用来源；会话目录外的来源不会被自动搬入。`training_archive.sh`用于自包含已停止会话的打包/校验/恢复；外盘用于归档，训练工作目录放本机合适文件系统。

旧memmap三物理区和仿真ring后端仍保留，不自动转换成cached。见 [缓存教程](../../tutorials/cached_replay.md)、[旧磁盘后端](../../tutorials/transition_replay.md)、[存储位置](../interfaces/local-storage.md)。

已有真实单帧重建、双池淘汰/并发采样和恢复证据；这些不保证任意数据完整、长期冷盘性能或进程内存严格上限。当前仍没有任意RL checkpoint另起空池的通用入口。

开发历史（按需）：[数据与缓存归档](../archive/replay/README.md)。
