# 经验池与存储历史

记录磁盘后端、共享双池、单帧存储、数据搬迁和完整恢复演变。10月24日增加相机断流旧图入池审计及20回合清理；清理不撤销旧权重学习影响，也不返还累计回合名额。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/replay.md)。

## 阶段记录

- [2026-10-02：磁盘 HIL 经验池与后台预取](records/training/chronicles/2026-10-02-disk-replay.md)
- [2026-10-03：历史实验数据外置归档（复制完成，迁移暂停）](records/training/chronicles/2026-10-03-experiment-data-archive.md)
- [2026-10-05：完整 transition 磁盘导入与在线分流 API](records/training/chronicles/2026-10-05-transition-replay.md)
- [2026-10-07：独立示范/在线双池与固定初始示范](records/training/chronicles/2026-10-07-dual-replay.md)
- [2026-10-09：local 冷数据迁到 omi_proj_data/local](records/training/chronicles/2026-10-09-local-data-relocation.md)
- [2026-10-09：`local/rl_training` 占用与迁移可行性核查](records/training/chronicles/2026-10-09-rl-training-storage-migration.md)
- [2026-10-10：共享内存 Demo/RL 双池实现与真实数据验证](records/training/chronicles/2026-10-10-cached-dual-replay.md)
- [2026-10-10：固定 BC12045 现场运行、单帧存储与 EEF 检查](records/training/chronicles/2026-10-10-fixed-bc-storage-live-review.md)
- [2026-10-10：async RL 回合观测按单帧存储](records/training/chronicles/2026-10-10-observation-frame-storage.md)
- [2026-10-10：旧格式与 SDK 错误回合迁移](records/training/chronicles/2026-10-10-old-and-sdk-episode-archive.md)
- [2026-10-11：缓存门槛修正与第一轮有界离线实验](records/training/chronicles/2026-10-11-cached-offline-exp01.md)
- [2026-10-11：新缓存在线采集与训练会话启动](records/training/chronicles/2026-10-11-cached-online-start.md)
- [2026-10-11：外盘归档与真实buffer恢复验证](records/training/chronicles/2026-10-11-external-archive-restore.md)
- [2026-10-11：问题采集数据归档，原路径恢复BC空池会话](records/training/chronicles/2026-10-11-invalid-data-reset.md)
- [2026-10-24：外部相机断流、旧图入池审计与20回合清理](records/training/chronicles/2026-10-24-external-camera-outage-cleanup.md)

## 原机制与领域摘要

- [双池共享内存缓存与全量磁盘索引](records/training/evolution/cached-replay.md)
- [磁盘 HIL 经验池](records/training/evolution/disk-replay.md)

## 旧教程与导航快照

- [Oct 11在线RL归档、恢复与buffer重建](tutorials/oct11_archive_restore.md)
