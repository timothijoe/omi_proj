# local 大数据存储与外接盘路径

## 2026-10-10：选定旧格式与SDK错误回合归档

当前BC评估目录的12个旧格式回合，以及此前BC12045异步RL试跑目录的4个SDK拒绝回合，
已迁到 `/home/zhoutong/Downloads/oct10/old_version_data/`，按相对 `local/` 路径保留层级。
此批原位置不留软链接；历史回合路径需按归档 `manifest.json` 映射，恢复说明见归档 `README.md`。
共16回合、2909文件、2,290,450,334字节，全部文件SHA-256核对一致。
当前BC工作目录仅保留19个单帧格式回合、3617条动作；模型、训练片段与replay不变。
该Downloads归档在本机同一文件系统，不是下面的外接盘冷数据迁移，也不释放整盘空间。
详细筛选与保留项见[迁移编年](../training/chronicles/2026-10-10-old-and-sdk-episode-archive.md)。

## 2026-10-09：外接盘迁移

更新：2026-10-09。本次迁移已完成，逐目录状态与空间数字见
`local/storage_migrations/20261009_202357/manifest.json`。
完整迁移清单见 `manifests/local-storage-20261009.json`。

本机 local 实际占用由 110.88 GiB 降至 36.66 GiB，
释放约 74.23 GiB。57 个目录、12326 个文件已逐文件校验。

## 两个 local 的关系

项目工作路径为 `/home/zhoutong/omi_folder/omi_proj/local/`，外置数据根目录为
`/media/zhoutong/zt-think-d1/omi_proj_data/local/`。迁移时保留相对于 local 的目录层级，
只迁出选定的冷数据。项目 local 本身仍是本机目录；迁出的目录在原位置建立绝对软链接。

例如 `local/eef_bc` 指向外盘 `omi_proj_data/local/eef_bc`，而
`local/rl_training/async_20261007_01` 指向外盘同名子目录。
`local/rl_training`、`local/rl_episodes`、`local/bc_episodes`、`local/wrench_live`
和 `local/tactile` 的父目录留在本机，允许新会话选择新的本机子目录。
软件仍可使用原命令和报告内的绝对工作路径，不改写原始数据、哈希或实验来源记录。
挂载点须保持上述名称；盘未挂载时，外置目录的链接不可用。

## 迁移范围

| 数据 | 迁移选择 | 原因 |
| --- | --- | --- |
| 旧 RL 会话 | `alternating_20261007_01`、`async_20261007_01`、`async_20261007_20s_01`、`bc_demo_new_20261007_213643_rl_probe_01`、`bc_protected_20261007_01`、`bc_protected_dual_20261007_01`、`offline_20261006_v1`、`seed_20261007_20s_01` | 完整冷归档；八份 replay/检查点共约 40.8 GiB 实际占用 |
| 人工采集历史 | `rl_episodes` 下除 `demo_new_20261007_213643` 外的既有子目录 | 保留原始回合、审核与训练片段；当前新示范留本机 |
| BC 评估历史 | `all8_coarse_fine_eval_01`、`bc_ready_20261007_01`、`overfit_71960_eval_01` | 固定模型与旧评估审计 |
| 数据集 | `datasets`、`eef_bc`、`passive_bc_20261005_wrench`、`bags` | 离线数据与历史实验产物 |
| 大缓存与诊断 | `tactile/replay_cache`、`recorded_review`、`wrist_recorded_review`、`grid_recorded_review`、`four-demo-audit-20261005`、`sensor-decoupling-20261005`、`zero-action-live-20261005`、`policy_gamepad` | 历史显示缓存与输入审计 |
| 传感器测试和力记录 | 三个 `sdk-dashboard-check-*`、两个 `sensors-smoke-*`、`wrench_live` 下既有会话 | 原始 bag/曲线/报告完整保留 |

## 本机保留

- 当前真机 RL：`rl_training/bc_demo_new_20261007_213643_rl_live_01`。
- 对应新种子、BC12045、BC 索引：`bc_demo_new_20261007_213643_rl_seed_01`、
  `bc_demo_new_20261007_213643_coarse_fine_01`、`bc_index_demo_new_20261007_213643`、
  `bc_seed_demo_new_20261007_213643*`。这些名称均相对于 `local/rl_training/`。
- 原始新示范 `rl_episodes/demo_new_20261007_213643` 和最新固定 BC 评估
  `bc_episodes/demo_new_20261007_213643_eval_01`。
- `.venv`、`cuda-env`、其他 Python 环境、厂商 SDK、ROS 构建、预训练权重、模型资产、
  当前 `eef_history` 策略、record010 零载荷基准及小型配置。

## RViz 原包与显示缓存

三份代表录包的原包本体仍在本机 `/home/zhoutong/omi_folder/representative_rosbag/october/`。
现有回放脚本从命令参数指定的原包生成或复用显示缓存，再发布给 RViz；
`local/recorded_review`、`local/wrist_recorded_review`、`local/grid_recorded_review` 和
`local/tactile/replay_cache` 已外置，因此这些录包回放入口仍需挂载移动盘。
`local/bags` 中四个手柄训练示范包是另一批数据，不是三份代表原包的替代位置。
现场实时 RViz 直接订阅现场话题，不读取上述录包缓存。
原包、缓存和训练包的对应关系见[RViz 操作页](../../../tutorials/rviz_representative_bags.md#原包显示缓存和训练示范包)。

## 恢复与后续写入

外盘为 exFAT，不支持 Unix 软链接和完整 Unix 权限语义；软链接建在本机 ext4 上。
本次迁移验证文件内容与目录结构，并记录原模式和修改时间；不宣称保留原所有者、权限或稀疏分配。
旧 RL replay 的 `.npy` 稀疏数组复制后可能占用接近表观大小。

迁出的 RL 会话供归档与只读查看；尚未验证在这块 exFAT 上进行 replay mmap 写入、
写锁、原子检查点和中断恢复。需要恢复旧会话训练时，先停止相关进程，复制完整外盘目录到
本机 SSD 的临时目录，核对清单的逐文件 SHA-256，再将原位置软链接替换为本机目录。
只复制 `actor.pt` 不能恢复完整 Learner、replay 或来源关系。

新训练/采集使用本机父目录下的新会话名；不要对外置旧会话直接执行 `--resume`。
`datasets`、`eef_bc` 和已迁出的显示缓存整个目录都在外盘，其下新建文件也会写入外盘；
需要本机性能时显式选择另一个本机输出目录。旧报告中的路径保持原文，链接负责兼容。

本次外盘目录独立于 10 月 3 日的 `legion_data/.../oct_02` 和
10 月 7 日的 `omi_rviz_archive_20261007`；三个归档不能相互替代。
操作检查见[存储教程](../../../tutorials/local_data_storage.md)，逐阶段事实见
[迁移编年](../training/chronicles/2026-10-09-local-data-relocation.md)。

## 同日主机空间清理与内核备份

以下是 local 数据迁移完成后的独立操作；上文和迁移编年的空间数字是迁移完成当时的快照。

- 清理用户 pip/npm 下载缓存约 11.2 GiB，未卸载已安装的环境或工具。
- `/usr/local/src/legion-aw88399-7.1.6/` 是 AW88399 音频修复所用的定制 Linux 内核源码与构建目录，
  不是 Codex 安装目录。完整目录先压缩备份并逐文件 SHA-256 校验，再删除 80065 个生成文件，
  释放 27.72 GiB，目录由约 31.71 GiB 降至 4 GiB。
- 本机保留源码、音频补丁、配置、Module.symvers、生成头文件、scripts/tools、vmlinux 和签名材料。
  `/boot` 与 `/lib/modules/7.1.6-dirty` 中已安装内核、启动镜像和全部模块清理前后校验一致，
  AW88399 音频模块仍加载；未重启或进行音频播放测试。
- 2026-10-09 20:58 完成时根分区可用空间约 137.26 GiB；这是上述清理后的快照，不是实时余量。

完整压缩备份约 7.53 GiB，位置：
`/media/zhoutong/zt-think-d1/legion笔记本历史性质的备份/历史备份/legion-aw88399-7.1.6_20261009_205101/`。
目录内 `README.md` 给出恢复命令，`SHA256SUMS`、`source-manifest.json`、
`archive-verification.json`、`cleanup-plan.json` 和 `result.json` 保存校验与清理证据。
本机记录位于 `local/storage_migrations/kernel_build_cleanup_20261009_205101/`。
归档保留 Linux 权限、所有者和链接，恢复应解包到本机 Linux 文件系统。
它属于主机内核历史备份，与 `omi_proj_data/local` 的项目冷数据归档分开管理。
