# 当前训练说明与文档汇总

最新补充：2026-10-17。[SpacePilot/BC6148纪传](agent/training/evolution/spacepilot-bc-online-rl.md)、[当天编年](agent/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)和[显式参数操作页](../tutorials/spacepilot_bc6148_online_rl.md)记录当前30秒/300回合任务，用户已启动在线采集和训练。

下文保留2026-10-12整理的Oct10–11任务说明及通用操作分类；Oct17实际操作优先读上方专页。
旧任务操作见[真机常用指令](../tutorials/common_live_commands.md)，所有项目Markdown可在
[全量索引](markdown_index.md)查找。日期编年是当时证据，不应将其中旧目录、batch2或30秒示例当作当前默认。

## 先分清五种操作

| 操作 | 从哪里开始 | 是否保留旧训练数据/进度 | 操作入口 |
| --- | --- | --- | --- |
| 从BC新采一批、重新学习 | 原BC Actor与归一化 | 不保留；新Critic/优化器/计数，空Demo/RL | [新建空池](../tutorials/common_live_commands.md#rl-new)，再启动在线入口 |
| Ctrl+C后继续同一任务 | 原任务的完整checkpoint | 保留数据、优化器、累计更新数 | [原任务续跑](../tutorials/common_live_commands.md#rl-resume) |
| 在新目录恢复外盘归档 | 完整run.tar | 保留归档的完整状态和数据 | [归档恢复](../tutorials/common_live_commands.md#archive-restore) |
| 固定BC评估 | 固定BC checkpoint | 只录制和推理，不运行Learner | common_live_commands中的固定BC入口 |
| 任意RL checkpoint另起空池 | 指定RL模型 | 预期只继承权重，清空数据/学习状态 | **尚无通用初始化入口，不能套用BC prepare命令** |

“新文件夹”可以是重新学习，也可以是完整任务的恢复副本，两者不能混称。
`--bc-run`目前指定BC来源目录，读取其actor.pt；不是一个可接受任意BC/RL `.pt` 文件的通用参数。
不要仅拷贝actor.pt覆盖某个已有任务，其Learner、优化器和replay可能仍属于另一版本。

## 在线RL为什么没有resume参数

用户当前这条 `run_async_rl.sh --run local/rl_training/bc12045_newdata_30s_20261011_01 ...`
就是自动续跑。代码的实际路径为：

1. `hil/async_training.py`校验并读取该目录的config/session，Actor加载actor.pt。
2. `hil/learner.py`发现learner.pt后调用 `SAC.restore`，恢复完整网络、优化器、温度、计数和保存的随机状态。
3. 已有replay通过 `open_replay` 打开，cached后端从SQLite及原始帧重新构建内存工作集。
4. 正常关闭时再次发布checkpoint；下一次启动继续同一目录，不执行prepare，不从零开始。

**在线RL没有 `--resume` 开关。** 上层 `run_bc_episodes.sh --resume` 是固定BC评估的另一套CLI，不能互换。
新建任务也用同一个在线启动命令，是因为prepare已经生成版本0的预加载模型和空池；
此时“加载已有文件”指刚生成的初始状态，而旧任务则加载已经学习过的状态。

权重/超参数可恢复不等于旧内存布局逐位恢复：缓存成员及采样次序可能变化，不能承诺位级训练复现。
batch、探索、检查间隔等本次运行选项仍应显式写在命令里，见常用指令D5表格。

## 最后确认的可运行基线

| 项目 | 当前基线／最后保存状态 |
| --- | --- |
| 本机任务 | `local/rl_training/bc12045_newdata_30s_20261011_01/` |
| 状态 | Oct 11正常CLOSED，本次整理再次读取仍CLOSED，无error |
| 原BC | BC12045，来源 `local/bc_episodes/demo_new_20261007_213643_eval_01/actor.pt` |
| 最终checkpoint | actor.pt与learner.pt均16677，最后现场执行版本16150 |
| 当前回合时限 | 45秒，目录名30s是历史名称 |
| batch / 预热 | 64 / 1000次Critic-only，续跑不重做已经完成的预热 |
| 当前gamma / 编码器 | 0.98 / 整体冻结，触觉也冻结；两者仅记录待改，未调整 |
| 采样与BC约束 | 正常Critic批次Demo/RL各半，人工标签只来自本批新数据，BC参考为原BC模型 |
| 探索 | std0.05、clip0.15，归一化tanh后加噪，人工动作不加噪 |
| 权重交接 | Learner每50次更新发布；Actor每新增10个有效回合检查，重启立即加载最新 |
| 更新预算 | 1000＋已登记online条数×1；Actor等待Start时Learner仍可学到上限 |
| 内存 | 两池合计16 GiB驻留目标、20 GiB受管管线限制，非整个进程RSS或显存上限 |
| 数据 | SQLite已登记53513条，其中9754人工，固定旧seed0；另449条末回合已保存待补登记 |
| 原始回合 | 140个：成功64、timeout69、人工提前结束5、异常2；人工标记成功不等于自主成功 |
| 数据存储 | 单帧共享＋十帧窗口引用，加载时重建history；不是只往前找十条动作 |

完整基线及历史证据见[可运行版本记录](agent/training/chronicles/2026-10-11-runnable-baseline.md)。
当前目录可以直接续跑，不能再次prepare。若想重新只用新采集数据，创建另一个目录并用weights-only初始化。
新会话按当前命令需先有100条有效人工数据入池；仅有策略数据无法替代Demo。

## 文档按问题查找

| 你要查什么 | 主要说明 | 对应事实记录 |
| --- | --- | --- |
| 接收端、相机、触觉、BC/RL命令 | [常用现场指令](../tutorials/common_live_commands.md) | 该页保留现场硬件参数，RL部分按本次基线更新 |
| 新建空池、自动续跑、参数来源 | [common D部分](../tutorials/common_live_commands.md#rl-new) | [weights-only实现](agent/training/chronicles/2026-10-11-weights-only-new-data.md) |
| 单帧保存与十帧重建 | [异步RL存储说明](../tutorials/async_rl.md#2026-10-10回合观测按单帧存储) | [单帧验证](agent/training/chronicles/2026-10-10-observation-frame-storage.md) |
| Demo/RL共享与滚动淘汰 | [缓存教程](../tutorials/cached_replay.md)、[机制](agent/training/evolution/cached-replay.md) | [共享与独立淘汰验证](agent/training/chronicles/2026-10-10-cached-dual-replay.md) |
| 旧数据能否重建后训练 | [恢复接口](../tutorials/oct11_archive_restore.md) | [原始数据Learner验证](agent/training/chronicles/2026-10-10-recorded-bc-learner-validation.md) |
| 探索如何加、如何记录 | [在线探索](agent/training/chronicles/2026-10-11-online-exploration.md) | [batch64实际记录](agent/training/chronicles/2026-10-11-batch64-exploration-live.md) |
| 确认Actor是否换模型 | [网页说明](../tutorials/training_monitor.md) | [在线会话交接](agent/training/chronicles/2026-10-11-cached-online-start.md) |
| buffer存量、未成功/timeout/异常统计 | [监控与回放命令](../tutorials/common_live_commands.md#monitor) | [双池可视化](agent/training/chronicles/2026-10-11-30s-buffer-dashboard.md) |
| 异常/问题数据清理及45秒时限 | [新建时限设置](../tutorials/common_live_commands.md#rl-new) | [两次归档重置](agent/training/chronicles/2026-10-11-invalid-data-reset.md) |
| gamma太小、触觉冻结 | [待改事项](agent/training/chronicles/2026-10-11-tactile-gamma-pending.md) | 只记录，未实现解冻或更改gamma |
| 首轮离线实验、负Q与奖励命中 | [首轮](agent/training/chronicles/2026-10-11-cached-offline-exp01.md) | [1000/4000预热对照](agent/training/chronicles/2026-10-11-critic-diagnostics.md) |
| 外盘到底存了什么、怎么复现 | [归档恢复教程](../tutorials/oct11_archive_restore.md) | [实际恢复验证](agent/training/chronicles/2026-10-11-external-archive-restore.md) |
| EEF缺失与早期固定BC采集 | [固定BC现场记录](agent/training/chronicles/2026-10-10-fixed-bc-storage-live-review.md) | [旧格式/SDK异常数据迁移](agent/training/chronicles/2026-10-10-old-and-sdk-episode-archive.md) |

## 监控的目录与端口

训练和监控的 `--run` 必须相同：本机任务用原路径，恢复副本用解包路径，新批次用新生成的路径。
网页通过命令读取目录，不在浏览器里挑选文件夹。现有Oct 11任务使用 http://127.0.0.1:8771/；
另一个任务可换8772/8773等空闲端口。新终端需要重新填写目录变量。
“Actor已加载”是执行版本，“最近发布”只是磁盘新版本；驻留buffer数量也不等于磁盘总量。
停止训练后网页可继续显示历史快照；关闭网页或监控不会停止训练。

## 外盘与本机文件

外盘归档根目录：`/media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data/`。
run.tar包含完整数据和状态，checkpoints/便于单独取用最终模型，initial_bc/保留原BC，README/工具/验证报告随包保存。
逐文件校验、实际恢复到本机、buffer重建及模型恢复均已验证。本机原目录没有删除。
外盘此前已安全卸载并关闭设备；使用外盘归档前需要重新连接/挂载。本次文档整理只更新本机，未改已校验归档。

## 当前仍未实现或未解决

- 任意RL checkpoint→新目录空buffer的通用初始化入口。
- 触觉编码器解冻及相应预热/优化器恢复设计；gamma与长时稀疏成功奖励的对照。
- 成功样本优先采样；当前仍为两池内均匀抽样。
- 接收端回执静默和SDK拒绝等现场异常的彻底解决。
- batch64/128容量与Actor并发延迟的系统对照；64已现场运行，但不能宣称最优。

完整历史按日期保留在[训练编年索引](agent/training/chronicles/README.md)。
全项目Markdown的路径和标题见[Markdown全量索引](markdown_index.md)，包括其他硬件、传感器、仿真和设计文档。
