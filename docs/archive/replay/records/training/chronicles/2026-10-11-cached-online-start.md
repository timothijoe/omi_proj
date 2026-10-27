> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-cached-online-start.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/replay.md)；本页保留原过程与证据。

# 2026-10-11：新缓存在线采集与训练会话启动

后续更新：[受限高斯探索与权重交接](../../../../online-rl/records/training/chronicles/2026-10-11-online-exploration.md)。
下文命令记录首次无探索启动；带探索的续跑命令见后续记录。17:53:55会话已正常关闭，Learner保存至4777。

用户明确本次要开启真机在线采集并同时训练。此前给出的 `run_cached_offline_experiment.py`
用于有界离线实验，不是本次现场入口；现已改用 `run_async_rl.sh`。
助手完成新会话准备并给出命令，随后只读检查确认用户已启动在线会话。本记录整理时未停止或重启现场进程。

## 会话与数据

| 项目 | 内容 |
| --- | --- |
| 在线会话 | `local/rl_training/bc12045_cached_online_20261011_01/` |
| 原始BC来源 | `local/bc_episodes/demo_new_20261007_213643_eval_01/actor.pt`，BC12045 |
| 初始化 | 完整Actor逐张量一致，RL更新计数从0开始；未使用exp01/02/03或manual离线实验权重 |
| 初始示范 | 1387条、11个训练片段，固定Demo区 |
| 历史录制来源 | 上述BC会话的19个单帧回合，后台只读登记；不是离线实验的16/3划分 |
| Replay后端 | `omi-cached-dual-replay-v1`，独立Demo/RL采样索引，共享人工transition内存 |
| 内存 | 驻留目标16 GiB，受管数据管线上限20 GiB；不是整个进程RSS或显存上限 |
| 训练 | batch2；前1000次Critic预热；编码器冻结，BC权重10，Actor学习率1e-5 |
| 权重 | Learner每50次更新发布；Actor每10个有效回合检查最新权重 |
| 更新预算 | `1000 + 已登记在线transition数 × 1`，累计预算；用完等待新数据 |
| 回合与控制 | 每回合20秒，10Hz观测驱动，`after-inference`仲裁 |
| 夹爪 | 用户暂定保持闭合，`--no-gripper`禁用A/B控制；此选项不主动执行闭合 |

新录制位于本在线会话的 `periodic_episodes/<episode>/`：`frames/`保存单帧，窗口引用重建十帧历史。
`replay/catalog.sqlite3`保存源索引，`actor.pt`/`learner.pt`是本在线会话的模型。
历史来源仍在原BC目录，不能把只保留新会话目录当作完整数据备份。
正常训练批次继续Demo/RL各半、池内均匀采样；成功样本优先采样尚未实现。

## 在线启动命令

新会话已经准备好，无需再次初始化。保持接收端、外部RGB、腕部ROI、触觉与EEF反馈运行，
同一时刻只保留一个动作发送入口，不同时运行独立手柄、固定BC或另一套RL控制。

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_cached_online_20261011_01 \
  --actor-device cuda \
  --learner-device cuda \
  --batch-size 2 \
  --publish-every 50 \
  --reload-every-episodes 10 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --no-gripper \
  --execute --enable-policy
```

- Start（315）开始回合；RB＋摇杆人工接管；308标记成功，307提前结束。
- 人工复位在回合外进行，不作为训练动作入池。
- Learner后台运行，详细日志在会话的 `learner.log`；Actor终端显示回合与策略加载状态。
- 首次从原BC开始；以后重复启动本会话会加载其最新RL权重，不会重新回到原始BC。
- `Ctrl+C`正常关闭本次Actor/Learner，独立传感器与接收端不随之关闭。

彩色提示来自在线回合入口，直接在终端执行时显示；通过 `tee` 管道或设置 `NO_COLOR` 时可能无颜色。
是否成功启动应看 `POLICY_LOADED`、`WAIT_START`、Learner心跳与更新计数，不能单凭颜色判断。

## 网页入口

训练状态网页（另开终端）：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_cached_online_20261011_01 \
  --port 8768
```

打开 **http://127.0.0.1:8768/**。这里的run直接指向在线会话，末尾不再加 `/run`；
此前离线实验的监控才指向实验目录下的 `/run`。

新会话回合画面回放可另开：

```bash
bash scripts/view_rl_episodes.sh \
  --run local/rl_training/bc12045_cached_online_20261011_01 \
  --port 8766
```

打开 **http://127.0.0.1:8766/**。此前恢复的8765回放服务指向原BC录制的19个回合，
不会自动切换到新在线会话。关闭任何监控/回放服务均不会结束训练。

## 实际现场快照

只读核查时间：**2026-10-11 17:46:55，Asia/Shanghai**。
以下来自运行中的JSON与audit，不是停止后的最终统计；文件分开读取，允许相邻更新之间存在差异。

- Actor：`WAIT_START`，已完成1个回合，当前 `policy_version=0`，换权重间隔10。
- Learner：`TRAINING`，Critic累计3976次，当前进程Actor更新1488次，最近发布版本3950。
- 此时训练预算4249次，历史源仍在导入，尚有3个pending回合；预算会随登记数量增加。
- Replay目录计数：初始示范1387，online3249，其中人工2049；驻留独立记录4451，淘汰0。
- 受管内存峰值10,190,278,268字节，约9.49 GiB；`loader_busy=true`、`loader_error=null`。
- 首个现场回合 `c8e10051d4e3413a8abec2f6062c5fa6`：timeout，未标成功；200个动作节拍，
  198条有效transition，2条因 `no_action_candidate` 排除，`training_ready=true`，使用单帧存储。

这些证据确认Learner已训练且发布权重；Actor仍为0是因尚未达到10个有效回合的换权重检查点。
这里的RL版本0对应初始化时完整继承的BC12045，不代表随机策略或BC丢失。
尚未确认新RL权重已被真机Actor加载，也没有根据首个超时回合推断策略优劣。

## 已执行的准备命令（仅供追溯）

下列命令已成功执行，`bc_initialization.json`确认 `initial_actor_exact=true`。
不要对现有目录重复执行；若要另起原BC对照，必须换全新的目标目录。

```bash
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run local/rl_training/bc12045_cached_online_20261011_01 \
  --replay-backend cached \
  --cache-target-gib 16 --cache-limit-gib 20 \
  --critic-warmup-updates 1000 \
  --recorded-source local/bc_episodes/demo_new_20261007_213643_eval_01
```

相关记录：[缓存机制](../evolution/cached-replay.md)、[负Q离线诊断](../../../../online-rl/records/training/chronicles/2026-10-11-critic-diagnostics.md)、
[在线监控教程](../../../../../../tutorials/training_monitor.md)。
