# 2026-10-10：async RL 回合观测按单帧存储

用户要求：首个 observation 保留完整十帧，其后只保存当前帧，从回合历史重建模型窗口，减少约十倍重复存储。

## 实现与兼容

新增 `hil/observation_storage.py`，将历史窗口拆为原dtype单帧，以内容SHA-256去重。
正常连续采样N个窗口只需N+9帧；相同内容可进一步共享。十帧引用记录实际窗口槽位，
精确保留初始历史、零占位、mask、跳采样与旧推理候选，不能用最近十条动作替代观测历史。

`PeriodicAudit` 的独立观测、动作和边界共享同一回合帧库；`periodic_replay.convert`
生成的ready片段也引用该帧库，不重复落盘observation/next_observation。
`read_episode`、BC数据读取、Replay导入、`PeriodicReview`通过公共读取器恢复完整数组。
写帧和引用均临时文件/fsync/原子替换，发布引用前先完成对应帧；读取校验哈希并使用有界缓存。

新格式 `omi-observation-frames-v1` 默认用于新的periodic回合，旧内嵌NPZ兼容。
适用async RL、人工周期采集和周期BC评估；旧receipt格式保持。
固定容量memmap replay仍存完整窗口，未改容量、训练采样、模型、动作或入池语义。
新片段依赖 `periodic_episodes/<source>/frames/`；归档需保留与 `episodes/` 的相对位置。
未修改已有录制数据、检查点或经验池，未连接机器人、重启训练或控制进程。

## 真实数据空间与一致性验证

只读来源：`local/rl_training/bc12045_obs_after_inference_20261009_01/periodic_episodes/29c01fe5df4544a9a229b30da1a33e3e`。
在临时目录转换，结束后临时副本清理；原始回合保持原格式。

| 范围 | 原NPZ字节 | 单帧格式NPZ字节 | 原/新 |
| --- | ---: | ---: | ---: |
| 182份独立观测 | 157,174,967 | 17,148,313 | 9.1656 |
| 加178条动作及1份结束边界，共361个窗口 | 311,877,461 | 17,589,509 | 17.7309 |

共191份单帧，正好182+9。361个窗口全部字段shape、dtype、C顺序原始字节完全一致。
表格比较压缩NPZ文件长度，包括帧库和引用文件；不含JSON/日志、文件系统块分配或固定容量replay。
完整转换加逐窗口读取核对耗时15.89秒，不是现场控制延迟或纯写盘吞吐基准。

## 软件验证

152 passed、2 skipped，命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_observation_storage.py tests/test_observation_driven_control.py \
  tests/test_periodic_control.py tests/test_arbitration_modes.py tests/test_async_episode_spool.py \
  tests/test_training_monitor.py tests/test_hil_runtime.py tests/test_hil_behavior_cloning.py \
  tests/test_offline_rl_pipeline.py tests/test_dual_replay.py tests/test_async_training.py \
  tests/test_bc_rollout.py tests/test_rl_episode_collection.py tests/test_protected_rl.py \
  tests/test_transition_replay.py
```

新增验证覆盖：首窗十帧及逐步只新增一帧、乱序读取和缓存数组独立、缺帧mask/非连续窗口、
旧格式、缺文件/损坏哈希/未知版本拒绝，以及真实形状的周期记录→片段→BC索引与加载→
Replay导入、重复导入幂等、逐帧图像渲染和整个运行目录移动。缺少回执仍按原规则切段。
两个跳过项为现有CUDA专项，本轮未进行GPU训练或真机并发性能验收。

正常退出并重启Actor/Learner后，新回合采用单帧存储；原命令无需新增参数。
当前机制见[真机在线RL](../evolution/real-online-rl.md#回合观测的单帧存储2026-10-10)，
读取与目录拷贝见[教程](../../../../tutorials/async_rl.md#2026-10-10回合观测按单帧存储)。

## 本轮交接：已完成与后续验证

本次存储改进已完成实现、离线验证和文档整理。用户确认后要求将当前进展保存到Markdown；
本节补充交接状态，以上测试和空间数字沿用本轮已执行结果，没有在整理文档时重新运行测试。

| 文件 | 本次职责 |
| --- | --- |
| `src/omi_hil_rl/hil/observation_storage.py` | 单帧去重、窗口引用、哈希校验、缓存与旧格式读取 |
| `src/omi_hil_rl/hil/periodic_control.py` | 后台记录观测、动作、结束边界及存储格式统计 |
| `src/omi_hil_rl/hil/periodic_replay.py` | 重建输入并导出共享帧的训练片段 |
| `src/omi_hil_rl/hil/exchange.py` | ready片段保存引用，读取时恢复完整transition |
| `src/omi_hil_rl/hil/periodic_review.py` | 逐帧查看兼容单帧引用格式 |
| `tests/test_observation_storage.py` | 无损重建、异常依赖、BC/Replay/查看与目录迁移验证 |

下一次现场运行：

1. 正常退出原async RL并等待保存完成，按原命令重启Actor/Learner。
2. 新回合保存后，检查 `audit.json.observation_storage_version` 为
   `omi-observation-frames-v1`，并核对 `stored_observation_frames` 和 `frames/`。
3. 用现有逐帧查看器查看首窗、回合中部和最后一条动作的十帧输入；确认新ready片段正常导入。
4. 观察真机并发采集/训练时写盘队列、保存耗时和实际目录占用；这部分尚无现场验证结论。

历史数据批量压缩、固定容量replay去重均不在本轮已完成范围。
此前SDK拒绝问题也不能由本次存储测试推断已经解决。
