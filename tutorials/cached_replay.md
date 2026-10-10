# 双池内存缓存：全量数据留盘，后台加载训练

新后端为 `omi-cached-dual-replay-v1`。Demo/RL各有采样索引，人工干预共享一份完整transition。
原始单帧数据留盘；后台校验、登记索引并重建内存数据，训练线程只从驻留数据随机采样。
已有磁盘ring会话保持原后端，不自动迁移或覆盖。
两池滚动独立：一侧移出不会使另一侧失去数据；只有双方都移出时才回收对应RAM缓存。
刚才的独立淘汰修正需要重启Learner才会加载新代码，已有SQLite目录不需要转换。

## 1. 从原始 BC12045 准备新的缓存会话

在项目根目录执行。下面是新的正式会话示例，验证目录中的测试权重不用于这里。
准备命令不连接机器人、不启动在线训练，初始Actor完整继承BC12045。

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run local/rl_training/bc12045_cached_20261010_01 \
  --replay-backend cached \
  --cache-target-gib 16 --cache-limit-gib 20 \
  --critic-warmup-updates 1000 \
  --recorded-source local/bc_episodes/demo_new_20261007_213643_eval_01
```

该命令拒绝覆盖已有目标。初始1387条人工示范只登记到固定Demo区；
`--recorded-source`指定本批19回合，Learner运行时自动读取完整audit，沿用回执与时序契约生成索引。
该来源可重复指定多个目录；不需要先运行旧的离线转换脚本，也不修改原BC的audit/ready标记。
未完成的staging回合不会导入；SDK等异常结束回合不会被当作有效在线经历。

这里的16 GiB是两池共享的驻留数据目标，不是每池16 GiB，也不是启动时立即预分配16 GiB。
20 GiB约束受管数据管线：驻留数据、加载工作空间、单帧小缓存、当前/预取batch及元数据预留。
**它不是整个进程RSS或整机内存的硬限制**，不包含CUDA、模型、Python/系统分配器额外占用及OS文件缓存。
GiB按 `1024³` 字节计算。初始示范必须能放入缓存，并给在线数据至少留两个位置，否则准备失败。

## 2. 先只运行 Learner

只读使用已录制的数据，不连接ROS、不发布机器人动作：

```bash
local/cuda-env/bin/python -m omi_hil_rl.hil.learner \
  --run local/rl_training/bc12045_cached_20261010_01 \
  --config local/rl_training/bc12045_cached_20261010_01/config.json \
  --device cuda --batch-size 2 \
  --min-online 100 --publish-every 50 \
  --max-updates-per-transition 1
```

可选更新预算为：累计Critic更新不超过 `预热步数 + 已登记在线transition数 × 参数值`。
例如本批3579条、预热1000步、参数1，对应累计4579步；不是每次重启额外4579步。
额度用完后等待新数据，Ctrl+C保存退出。参数1仅是可调整的起始设置，不代表已证明最优。
省略此参数沿用原来的持续训练行为。临时有界验证可另加 `--updates 20`。

缓存填充和登记均在后台。`stream_counts`显示内存可采样数量，`catalog_*`显示全量磁盘索引数量，
不会把两者混为同一个计数。正常批次严格Demo/RL各半，额外BC约束仅从Demo抽样。

## 3. 接回异步真机入口

需要在线采集时，正常退出单独Learner并保存，沿用传感器和接收端的现场启动流程，
只运行一套Actor/Learner。新会话使用：

```bash
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_cached_20261010_01 \
  --actor-device cuda --learner-device cuda \
  --reload-every-episodes 10 --batch-size 2 --publish-every 50 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference --execute --enable-policy
```

后端按会话自动识别，新完成回合自动登记并滚动进入缓存。
Actor仍遵循现有回合边界换权重规则；这个命令启动在线RL，不是固定BC评估。
原 `run_bc_episodes.sh` 仍只做固定BC；本次没有把它改成后台自动训练。

## 4. 监控、关闭和数据位置

现有训练监控增加：内存独立样本、磁盘在线/初始示范/人工干预数量、受管内存及峰值、上限和加载状态。
`status.json.replay`、`monitor/learner.json.replay`保存相同指标。

`replay/catalog.sqlite3`保存全量索引，`replay/manifest.json`保存契约、预算和来源目录。
不再为这个后端创建重复展开的 `.npy` observation池。缓存被淘汰后，磁盘索引仍保留；
再次选中时可重新读取。关闭时释放缓存，重启从索引重建，不重新计数已登记经历。

索引引用原始数据。备份或搬迁时，除运行目录外，还要保留初始示范源、`--recorded-source`目录以及
对应 `frames/`；不要在索引仍使用它们时单独删除或搬走。读取时发现文件/哈希变化会明确报错。
本运行目录自身的ready片段会补记 `catalog_registered=true` 的imported标记；
它表示已登记到磁盘索引，不保证全部数据同时常驻内存。外部来源文件保持只读。

机制与验证见[缓存双池](../docs/agent/training/evolution/cached-replay.md)。
