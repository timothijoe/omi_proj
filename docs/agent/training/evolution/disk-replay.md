# 磁盘 HIL 经验池

`training.disk_replay.DiskHILReplayBuffer` 是当前 SB3 单环境训练的可选存储后端。状态、图像、动作、奖励、结束/超时标记与在线/示范掩码使用 NumPy `.npy` memmap 存在磁盘，保持 [HIL 双流语义](hil-training.md#4-buffer-的存储与采样)。操作见 [磁盘回放教程](../../../../tutorials/disk_replay.md)。

## 数据流与接口

```text
环境 transition → 校验与复制 → 持锁写入 memmap → 发布 ring 位置
                                  ↓
双流抽样 → 后台读取并复制完整 batch → 内存预取 → 调用线程转为 Torch tensor
                                  ↓
                           SAC / 可选 BC 更新
```

`add()` 支持含状态和 RGB 图像的平面 `Dict[Box]` 观测，Box 动作与 `n_envs=1`。观测需带环境维 `(1, *shape)`；uint8 图像保留原始 dtype，不转为整池 float32。先校验并复制输入，再修改数组和路由掩码，防止无效输入部分覆盖旧记录。

基础数组由 `BaseBuffer` 元数据直接初始化，未先分配同容量 RAM 数组。当前观测与下一观测分别保存，正确保留终止帧、回合边界和离线不连续示范；第一版没有相邻图像去重、压缩或分块数据库。三路 128×128 RGB 的图像主体每个 transition 为 `2*3*128*128*3=294,912` 字节，20 万容量约 59 GB，另加其他字段。磁盘降低常驻匿名内存要求，不减少这个文件容量。

一个物理环形池包含在线和示范的两组逻辑索引，不是两个独立的大数组池。在线干预属于两流但只存一份；离线示范仅属示范流。容量可独立于训练步数固定，满后覆盖旧数据和旧标记；导入示范也可能被覆盖。默认每批两流各半，空流回退规则与内存池相同。超时沿用 SB3 timeout mask，不改变 reward 或已执行动作。

`sample()` 默认使用单线程后台预取一批；首批同步读取，之后消费之前准备的批次并启动下一批。`--no-replay-prefetch` 关闭预取。`sample_human()` 供 BC 同步抽示范。实际峰值还有当前 batch、待用 batch、张量复制和系统页面缓存，不能把“一批预取”解释成整个进程内存只占一批。预取样本是准备时的完整快照，可能来自刚被 ring 覆盖的旧经验；它仍是合法的离策略训练数据。预取会改变随机数消费时序，不承诺和关闭预取时逐位一致。

读 batch 和写记录共用线程锁；每批先进内存复制，再释放锁，不会返回混合了覆盖前后字段的 transition。只支持一个采样调用线程、一个 writer 进程；writer 与后台预取可并发。文件锁阻止同目录第二个进程打开写入，多个采集进程应在后续通过队列汇聚至一个 writer。

写入是同步的 memmap 拷贝，磁盘落盘由操作系统回写；第一版没有独立的异步写队列。随机读取、缺页或内存压力仍可能使 `add()` 等锁，不能宣称满足真机硬实时期限。完整池可使用可回收的文件页面缓存，RSS 仍可能随访问增长，并非严格的 RAM 配额。

## 保存、关闭与恢复

- `checkpoint()`：flush 所有数组并 fsync 文件，再原子写入 `manifest.json`、fsync 目录，发布干净的 ring 元数据。
- `close()`：停止预取、保存 checkpoint、释放 mmap 和进程锁；支持 context manager，重复关闭安全。
- `DiskHILReplayBuffer.reopen(path, device="cpu")`：读取干净 checkpoint，以 `r+` 重新映射，恢复位置、full、掩码和采样配置，可以继续写入和采样。
- 创建必须使用空目录，拒绝覆盖已有文件；新训练 CLI 不自动恢复旧目录。

每次 checkpoint 后，下一次修改会先将 manifest 标记为 dirty，再覆盖数据。强制退出或掉电后，如果 manifest 为 dirty，`reopen()` 拒绝恢复；这是有意避免将旧位置配上已被覆盖的数据。没有逐条写日志，也没有掉电后从旧 checkpoint 回滚数组的机制。普通退出可以保存，不能保证强制杀进程的数据完整性。

磁盘池不能使用 pickle；调用 SB3 `save_replay_buffer()` 会明确报错，应使用 checkpoint/reopen。磁盘训练保存 `replay/manifest.json` 和 `.npy` 数组，内存训练继续保存 `replay.pkl`。策略 ZIP 通过 `save_policy_checkpoint()` 保存为可独立加载的权重/优化器档案，序列化的 replay 配置切换为容量 1 的内存池，避免评估时打开原目录或分配大容量内存。恢复经验后要将 reopened buffer 显式挂到模型，完整环境/采集状态没有 CLI 自动续训入口。

目前基于 Linux `fcntl.flock` 与目录 fsync；不承诺 Windows 支持。目录迁移需要连同 manifest 和全部数组一起复制，操作应在 close 后进行。

## 训练入口

`sim_train --replay-backend disk` 启用磁盘，目录默认 `OUTPUT_DIR/replay`；`--replay-directory` 可覆盖目录，`--replay-capacity` 固定容量。默认后端仍是 memory，未指定容量时仍为 `max(1000, steps+demo_lines+1)`。metrics 新增后端、容量和磁盘数组总字节数。磁盘目录应放在已忽略的 `data/` 或 `local/`。

## 已验证与限制

2026-10-02 全部自动测试 **40 passed**。磁盘专项涵盖图像/状态/动作与内存池对照、双流采样、环形覆盖、超时、后台读取与写入的一致性、重开与继续更新、占用目录/多 writer 拒绝、进程异常退出后拒绝恢复、无容量级 RAM 初始化以及实际 SAC+BC 训练与策略加载。

本机 A 臂 200 步验证使用容量 64，完成 150 次 SAC 和 150 次 BC 更新，环形池保持 64 条；200 条录制校验通过，保存策略可独立加载评估。这个短跑成功率为 0/2，只验证数据链和更新，不证明策略收敛。

三路 128×128 RGB 的基准使用容量 512、1024 次写入、batch 64、100 批采样，数组主体 151,094,272 字节，含 checkpoint 测量。保留 OS 页面缓存时约 29.7 batch/s，采样 p50 33.6 ms、p95 41.0 ms，写入约 12,103 transition/s，checkpoint 约 0.228 s。进程峰值 RSS 约 462 MB，包含 Python/Torch 基线与 mmap/cache，不是经验池独占内存。这是小数据集缓存测试，不代表大池冷盘随机吞吐、GPU 训练吞吐或真机时限。

验证产物位于 `data/disk_replay_validation/`，未进入 Git。形成记录见 [开发编年](../chronicles/2026-10-02-disk-replay.md)。大于内存的数据池、多小时持续写读、图像训练任务和真机仍未验证。
