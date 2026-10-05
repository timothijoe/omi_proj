# 使用磁盘经验池

完整离线示范/在线transition指定目录导入、追加及Python写入API，见
[transition_replay.md](transition_replay.md)。当前BC代理标签不能直接导入。

先完成 [环境准备](environment_setup.md)，从 `omi_proj/` 执行。磁盘池支持图像字段，目前 OMI 的 A 臂到达任务仍只有数值观测。

## 运行训练

选择新输出目录；磁盘经验目录必须为空，避免覆盖旧数据。

```bash
source scripts/env.sh
python -m omi_hil_rl.training.sim_train --help
python -m omi_hil_rl.training.sim_train --scene "$OMI_TIANJI_SCENE" \
  --steps 1500 --demonstration-steps 500 \
  --later-intervention-probability 0.2 --evaluation-episodes 10 \
  --bc-weight 0 --entropy-initial 0.01 \
  --replay-backend disk --replay-capacity 2000 \
  --output-dir data/sim_runs/my_disk_replay
```

预期输出：`replay_backend=disk`，`replay_storage` 报告容量、已写条数、数组字节数和目录。`replay/` 下有 `manifest.json`、`writer.lock` 和 `.npy` 数组；策略为 `policy.zip`，没有 `replay.pkl`。容量满后覆盖旧数据。可用 `--replay-directory local/replay/my_run` 指定 SSD 上的新目录；`--no-replay-prefetch` 关闭后台预取，便于比较速度。

独立加载策略评估：

```bash
python -m omi_hil_rl.training.sim_eval \
  data/sim_runs/my_disk_replay/policy.zip --scene "$OMI_TIANJI_SCENE" --episodes 10
```

`Ctrl+C` 会通过 finally 尝试关闭并保存经验池；仍不保证当时已经保存策略。强制退出/掉电可能留下 dirty manifest，恢复时会明确拒绝。保留故障目录，另选新目录重新运行。

## 检查与恢复经验

训练退出、writer 释放目录后，可以使用 Python API：

```python
from omi_hil_rl.training.disk_replay import DiskHILReplayBuffer

with DiskHILReplayBuffer.reopen("data/sim_runs/my_disk_replay/replay") as replay:
    print(replay.storage_stats())
    print(replay.stream_counts())
    batch = replay.sample(64)
    print(batch.actions.shape)
```

没有训练中多进程只读打开或完整 CLI 续训功能。自行恢复模型更新时，先 `DemoRegularizedSAC.load(policy_path, env=compatible_env)`，再将 `model.replay_buffer` 指向 reopened buffer、`model.buffer_size` 设置为池容量，并使用 SB3 `learn()` 初始化训练上下文。策略和 replay 应来自同一已完成运行；环境、观测、动作、奖励配置必须一致。只 reopen 经验池不等于恢复整个训练现场。

## 测本机图像采样吞吐

下面会写入三路 128×128 RGB 的测试数据，数组约 151 MB，要求新目录：

```bash
python -m omi_hil_rl.training.replay_benchmark \
  --directory data/replay_bench/my_test \
  --capacity 512 --transitions 1024 --batches 100 --batch-size 64
```

结果在控制台及 `benchmark.json`，包括写入速度、checkpoint 耗时、采样 p50/p95、batch/s 和整个进程峰值 RSS。该测试保留系统页面缓存，不是冷盘性能测试。提高容量前先按观测 shape 计算文件体积并检查磁盘余量；图像前后帧目前分别保存，三路 RGB 每条约 295 KB。不要直接用 20 万容量测试而忽略约 59 GB 的文件需求。

## 常见问题

- `directory must be empty`：更换新目录；创建不会清理或覆盖已有池。
- `already open by a writer`：先退出持有该池的训练进程。
- `no clean checkpoint`：非正常退出后缺少可恢复 checkpoint，本版不支持自动修复。
- 磁盘读取慢或控制循环停顿：减少图像/容量、使用 SSD、比较关闭预取后的表现。本版依赖 OS 回写，未提供真机硬实时保证。

格式、锁和恢复边界见 [磁盘经验池说明](../docs/agent/training/evolution/disk-replay.md)。
