# 2026-10-09：local 冷数据迁到 omi_proj_data/local

## 用户要求与迁移选择

用户要求检查 `omi_proj/local` 为何很大，将适合迁出的内容移到
`/media/zhoutong/zt-think-d1/omi_proj_data/local`，并更新文档。
本次执行承接[此前只读可行性核查](2026-10-09-rl-training-storage-migration.md)。

本次迁移开始前，整个 local 约 111 GiB；主要是 rl_training 约 64 GiB、
rl_episodes 约 12 GiB、eef_bc 约 6 GiB、cuda-env 约 5.6 GiB、
tactile 回放缓存约 5.1 GiB、wrench_live 约 3.8 GiB、bc_episodes 约 2.9 GiB。
训练会话既保存原始周期/有效片段，又按容量预分配 replay，还保留 seed/probe/旧版本副本，
所以目录数和磁盘占用不能解释为同等数量的独立真机实验。

选定冷数据实际约 74.23 GiB、表观约 101.38 GiB、12326 个普通文件；
exFAT 不保留稀疏分配和完整 Unix 元数据，目标容量按表观字节和分配开销预算。
八个旧 RL 会话迁出；当前 live、对应 BC/seed/索引、新示范和最新 BC 评估保留本机，
Python/SDK/ROS 环境、模型和预训练权重也留本机。完整映射见[存储契约](../../interfaces/local-storage.md)。

## 执行与证据

状态：全部完成。每目录依次复制到外盘临时目录、逐文件 SHA-256 对照、检查源文件未改变、
复查打开文件和 mmap、确认挂载盘，最后以原路径软链接替换本机已校验副本。
只有外盘文件校验通过且兼容链接生效，才移除本机原副本；失败时保留未切换的源数据。

开始前没有相关训练/采集进程或选定目录的打开文件；所有检查到的 replay manifest 均为 clean。
本次不启动 ROS 或机械臂，不更新模型、不改变数据有效性和训练标签。

本机证据目录：`local/storage_migrations/20261009_202357/`。
外盘证据副本：`/media/zhoutong/zt-think-d1/omi_proj_data/migrations/20261009_202357/`。
`plan.json` 记录源占用和范围，`manifest.json` 记录每目录阶段与结果，
`files.sha256.jsonl` 记录全部相对文件路径、大小、哈希和原始模式/修改时间。

## 路径与使用边界

项目 local 本身与几个会话父目录保留本机；只对已迁出的目录建软链接。
旧命令和实验报告绝对工作路径仍可解析；源实验元数据和权重不批量替换字符串。
外盘未挂载时这些链接不可读，当前本机保留的 live/seed/示范不因此移动。

本次验证冷归档内容与只读访问；未验收外盘上的 replay 写入/锁/检查点恢复。
恢复旧 RL 会话须先校验并复制回本机 SSD，再恢复原工作路径。
本次目录与 10 月 3 日、10 月 7 日的历史归档分开管理，旧归档不是新的完整副本。
操作与恢复步骤见[存储教程](../../../../tutorials/local_data_storage.md)。

## 完成统计

57 个目录、12326 个文件全部完成 SHA-256 对照，原路径链接与目标目录数量/大小复核通过。

| 项目 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| 本机 local 实际占用 | 110.88 GiB | 36.66 GiB |
| 本机根分区可用空间 | 24.21 GiB | 98.43 GiB |

本机释放约 74.23 GiB；目标文件表观大小
101.38 GiB，外盘实际分配约 102.37 GiB，差异包含 exFAT 簇与目录开销。
完整映射与汇总见 `manifests/local-storage-20261009.json`。

迁后只读检查通过：57 个目录链接，12326 个目标文件的数量/大小，14 个干净 replay manifest，
264 个 NPY 数组的 shape/dtype 与只读 mmap，16 个检查点 ZIP 结构，4 个示范 bag 的全部分卷，
以及 15 个保留目录仍在本机。当前 RL 查看器仍识别 11 个目录（10 个完整审计回合和 1 个暂存）、
1059 条有效 transition。校验不更新模型、不写 replay，也不验证外盘续训。
