# 异步真机 RL：每 10 个完整回合检查新策略

## 2026-10-07 新 BC12045 热启动

新批次 `demo_new_20261007_213643` 已准备独立 RL 种子
`local/rl_training/bc_demo_new_20261007_213643_rl_seed_01`：11 个周期人工段、
1387 条固定示范；初始 Actor 参数与 BC12045 逐项完全一致。Critic 新建，编码器冻结，
前 1000 次更新只训练 Critic。`rl_probe_01` 是独立离线并发测试副本，
不要拿它当第一次真机运行目录。真机运行副本是 `rl_live_01`。

离线检查：新副本做 20 次 Critic 更新时，55 次录制观测推理的最长耗时为
11.52 ms，超 100 ms 为 0；没有创建机器人命令发布者。8 秒现场传感器只读检查
得到 62 次完整候选，0 次超过 100 ms，RGB、腕部图像、双指触觉和 EEF 均有消息；
它不验证实际接收端回执、运动效果或并发真机端到端时序。
本次接收端只读检查确认策略和手柄通道各有一个订阅者，检查时两个通道均无动作发布者，
`tactile_guard_enabled=false`。这些都是检查时的快照，正式启动前如现场状态变动需重查。

操作者在机械臂旁、确认路径和停止方式后，**只运行一个** RL Actor：

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc_demo_new_20261007_213643_rl_live_01 \
  --reload-every-episodes 10 --batch-size 2 --publish-every 50 \
  --execute --enable-policy
```

Start(315) 开始每个回合；未按 RB 时用当前固定版本的 BC/RL 策略，按住 RB(311)
立即切到摇杆人工控制，松开后恢复策略。308 标记成功，307 提前结束，Back(314)
仅在回合外回 home，Ctrl+C 退出 Actor 和 Learner。Learner 从启动即并行运行：
前 1000 次 Critic 预热可只用固定示范；其后须有至少 100 条有效在线 transition
才更新 Actor。完整且有效的源回合累计 10 个后，Actor 才检查并加载最新已发布权重；
这期间仍运行初始策略。Learner 状态见运行目录 `status.json` 和 `learner.log`，
回合状态见 `async_state.json`、`PERIODIC_SAVED` 和 `periodic_episodes/`。
RL 现在会在等待 Start、进入回合、收到成功/结束标记、写盘中和本地保存完成时，
追加彩色中文提示；原有英文及 JSON 状态行保留。结束后控制线程先停止动作，
再等待本地审计和训练片段写完，才允许进入下一回合。保存完成提示里的
“待 Learner 异步导入”表示片段已经写盘，**不表示** Learner 已经完成导入或更新；
实际导入和训练进度以 `status.json` 与 `learner.log` 为准。下一回合请等到
“等待第 … 个 RL 回合”出现后再按 Start；保存期间按 Start 不会跳过写盘。

这批 BC 的 12 个既有真机评估审计没有成功标记，离线拟合误差不能证明真机效果。
第一次运行应短时、有人随时握住 RB，并用 `PERIODIC` 行确认 `source`、`gate`、
`nonzero_action`、`receiver_verified`；若效果或回执异常，立即按 RB 接管或 Ctrl+C 停止。
触觉预警与触觉拦截仍保持关闭，不参与 BC/RL 动作决策。

以下章节保留早先 BC11795、1296 条示范的运行记录和机制说明；不要把旧目录
当作新模型测试。
当前 RL Actor 不启动 BC 的触觉差值预警；接收端触觉拦截默认关闭，最近一次现场只读查询
`tactile_guard_enabled=false`。只有操作者在**接收端启动命令**显式设置
`tactile_guard_enabled:=true` 才会让触觉保护影响模型动作。下文“BC保护式RL”指
BC参考约束与编码器/示范池机制，不表示触觉保护已经打开。

入口 `scripts/run_async_rl.sh`。Actor 与 Learner 同时运行；不再等待“本回合训练 N 步”。
用户确认的“10 条”是 **10 个完整有效回合**，不是 10 条 transition。

只想切换BC模型或播放成功label，请先看[现场测试速查](bc_replay_testing.md)。
本次BC/replay/训练实现的完整交接记录见[开发记录](../docs/agent/training/chronicles/2026-10-07-periodic-replay-bc-fitting.md)。

## BC保护式RL热启动（最新）

代码改动、测试证据、BC模型选择及视觉/触觉/历史帧冻结范围，统一见
[最新开发记录](../docs/agent/training/chronicles/2026-10-07-bc-protected-rl-and-encoder.md)。

最新双池目录为`local/rl_training/bc_protected_dual_20261007_01`，由旧保护式会话独立迁移，旧目录不覆盖。
BC11795全部Actor参数、共享编码器和归一化逐项一致地迁入；新建Critic头、target和优化器。
上句指BC热启动阶段；本次双池迁移完整保留已有Critic、优化器和训练计数，不重新初始化。
8个人工回合1296条全部作固定种子，无独立验证集。原BC与旧RL目录未改变。

```bash
# 已准备好，不需要再次初始化。先关闭其他动作发布进程，保持接收端和传感器运行。
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc_protected_dual_20261007_01 \
  --reload-every-episodes 10 --batch-size 2 --publish-every 50 \
  --execute --enable-policy
```

仍是315开始、RB手柄优先、308成功、307停止、20秒超时；Back回位仅在回合外。
一条命令监督Actor与Learner；Ctrl+C停止本次输出、写盘和Learner，不关闭外部设备服务。
每10个有有效训练段的完整源回合检查新权重；一回合切成多段也只计一次。
没有合格数据的回合只保存审计、不计入这10回合，不因单条回执迟到直接暂停整场。

保护设置：

- 共享编码器全程冻结（本阶段没有自动解冻）；前1000次更新仅训练Critic头，Actor和温度不更新。
- 此后每2次Critic更新进行1次Actor更新，Actor学习率1e-5；损失为SAC项加10倍human动作标签MSE。
- 固定BC参考不训练，日志提供`bc_loss`、`bc_reference_mse`、`bc_reference_max_abs`。
  漂移是当前采样批次的监测值，不是安全保证，也尚未自动回滚。
- `learner.pt`持久化参考BC、冻结配置、预热计数、优化器；恢复不会重新预热或随机覆盖BC。
- 目前Actor仍确定性推理，未新增随机探索。示范约束不保证策略只变好。

周期数据链路：主线程按100ms目标发命令，后台写原始`periodic_episodes/`。
结束后写盘线程检查命令ID、来源、坐标/数值、接收端接受时间、前后完整观测及时间顺序，
把有效连续段写到`episodes/*-segment-*/ready.json`，Learner独立导入。
标签是实际发布且被接受的归一化命令，**不是实测位移，也不把queue_accepted说成物理执行完成**。
允许观测间隔80–150ms；接受延迟超过50ms、RB中途打断、缺观测/回执、拒绝等会排除对应区间。
断档处以truncated结尾并保留bootstrap，不跨断档拼接；只有最后有效段到达真实结束边界才赋成功奖励。
成功结束但末段不合格时，`success_label_recorded=false`，不能把较早的动作补标成功。
异常或Ctrl+C中断回合保留审计、不入池。普通截断边界在停止前抓取；成功终止则允许记录停止后、
人工复位前的首个完整窗口（要求EEF确实更新），标注`terminal_success_stop_ns`。
这一步可能被成功停止缩短，不宣称执行了完整位移；success终止不bootstrap，绝不借用人工复位后的观测。
查看`PERIODIC_SAVED`的`transitions`、`segments`、`excluded`、`success_label_recorded`判断现场数据质量。
默认BC测试入口仍为audit-only，不会自动将以前的periodic审计导入。

离线验证：旧保护式目录完成4步Critic预热及44次GPU并发推理，p95=9.62ms、最大12.65ms；
真实BC的独立GPU测试验证：预热输出逐项一致、随后BC约束更新损失有限、编码器保持不变。
双池迁移后再完成4步demo-only预热，RL版本4→8，46次推理p95=11.03ms、最大13.09ms，无超100ms。
未创建机器人发布者；预热期间Actor不变，不是把BC11795换成了随机模型。
尚未实机验证新周期训练段的有效率、成功标签保留率或RL收敛。
双池已固定保留初始示范；正常RL更新仍未增加UTD预算，达到在线门槛后可以重复训练已有在线数据。

### 双buffer的数据去向与启动门槛

```text
replay/
  demo/initial/         固定初始人工示范，写入完成后封存，禁止覆盖
  demo/interventions/   在线人工干预，独立滚动容量（默认2000）
  online/               全部有效在线交互，独立滚动容量（默认4000）
```

逻辑上仍为“示范池＋在线池”，示范池内部有固定区和滚动区。人工干预进入interventions与online，
模型动作只进online；初始示范只进initial，不再伪计为新增在线交互。
初始8回合包括2个超时回合，保留原动作、奖励和终止标签，不改成全部成功。
在线失败/超时数据也保留，不按成功与否过滤有效交互。

正常RL每个偶数batch严格各取一半，batch2即示范1条＋在线1条；池内均匀、有放回采样，不是PER。
示范半批从initial与interventions所有保留transition的并集中均匀抽取，不是两个分区再各取一半。
同一个人工干预可能从两边都抽到，这是预期行为。BC额外约束批次只从示范池抽取，不用自主动作作人工标签。
“人工”是来源标记，并不自动证明每个动作都是高质量示范。

迁移完成时：initial=1296、interventions=0、online=0。Critic预热可以只用示范进行，日志
`demo_only_warmup=true`；累计1000步后若在线数据不足默认100条有效transition，Learner等待采集，
不会继续仅凭历史示范更新Actor。Actor/手柄仍可操作，等待训练不阻塞回合。
`status.json`提供`waiting_for_online`、`critic_warmup_remaining`与各池计数。
100条是入池后的有效transition数，不是100个回合；策略换权重仍按10个完整有效源回合检查。

旧目录不会自动改格式。需要迁移另一旧会话时，先关闭其Actor/Learner，使用新的目标目录：

```bash
bash scripts/migrate_dual_replay.sh \
  --source local/rl_training/bc_protected_20261007_01 \
  --run local/rl_training/bc_protected_dual_NEW \
  --intervention-capacity 2000
```

迁移验证原始训练索引和数据哈希，恢复固定初始示范，将旧池尚保留的非种子在线经验按时间顺序迁入。
被旧环形池覆盖的非种子在线经验不会凭空恢复；初始示范可从原始哈希验证文件恢复。
迁移会复制模型、完整Learner状态、回合文件及导入标记；源目录保留，活动写者/dirty池/未完成导入拒绝迁移。
原始训练文件必须仍可访问，磁盘须有空间容纳独立新副本。

双池使用同一Learner写入，跨池操作有顶层dirty标记。正常Ctrl+C和干净checkpoint可恢复；
checkpoint完成但imported标记未写时可以补记而不重复导入。硬崩溃造成半次跨池写入会拒绝重开，
需要恢复干净备份，不承诺任意断电自动修复。初始示范“固定保留”不替代独立数据备份。
实现和测试记录见[双池开发记录](../docs/agent/training/chronicles/2026-10-07-dual-replay.md)。

要重新准备另一个全新目录，可自定义保护参数（不会启动机器人）：

```bash
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/all8_coarse_fine_eval_01 \
  --run local/rl_training/bc_protected_NEW \
  --capacity 4000 --intervention-capacity 2000 --critic-warmup-updates 1000 \
  --actor-learning-rate 0.00001 --bc-weight 10
```

准备会验证原数据哈希和动作标签，拒绝覆盖已有目录。预热步数/权重是当前实验初值，不是已调优结果。
新准备目录默认使用双池；`--capacity`现在指在线池容量，初始固定区按训练样本总数分配。

## 当前可运行：固定 BC 自主操作与人工接管

### 2026-10-07：全部8回合两阶段BC拟合

按用户要求使用原索引全部8个有效人工回合，共1296条（6个成功、2个超时）。
原来2个验证回合也参与训练，**没有独立验证集**。从原多回合BC version295开始，
不是从单回合过拟合模型开始；保持输入、归一化、动作表示和网络结构不变。
冻结预训练视觉骨干，其余原有可训练编码器参数和输出头联合优化；batch16、seed7。
先4000步Adam lr=1e-4，再从第一阶段最好的3750步权重重新建立Adam，8000步lr=1e-5。
累计执行12000步，按所有训练样本MSE选择11500步模型，版本11795（295+11500）。

| 项目 | 原BC | 全8回合拟合 |
|---|---:|---:|
| 全量归一化动作MSE | 0.0462581 | 0.00088644 |
| 有明确dx标签的方向准确率 | 95.81% | 100% |
| 433条全零标签：每条最大绝对预测分量的均值 | 0.31522 | 0.04361 |

最终单轴平移MAE=0.01070/0.01260/0.01352mm，旋转MAE=0.00869/0.01075/0.00843度。
这些是存储观测上的预测误差，不是机械臂定位精度。最大单分量预测误差仍约0.629，
零动作标签上的最大绝对预测约0.186，不能凭均值声称所有动作都准确。
骨干权重未改变；GPU重载1296条输出最大差=0；原BC及单回合模型均保留。

训练产物：`local/rl_training/bc_all8_coarse_fine_20261007_01/`（report、history、
before_predictions、fit_predictions、actor）；独立真机评估快照：
`local/bc_episodes/all8_coarse_fine_eval_01`。

```bash
# 先关闭其他动作发布程序，人工复位，在可安全运动的位置测试一个回合
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/all8_coarse_fine_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

日志应显示version11795、OVERFIT_EVAL；315开始、RB优先、307停止、308成功、Ctrl+C退出。
运行的是网络根据实时传感器推理，不是标签replay。未验证真机运动或独立泛化。
复现入口（新目录）：

```bash
source scripts/env_ros.sh
local/cuda-env/bin/python -m omi_hil_rl.hil.fit_all_bc \
  --checkpoint local/bc_episodes/bc_ready_20261007_01/actor.pt \
  --output <新训练目录> --prepare-output <新评估目录> \
  --coarse-updates 4000 --fine-updates 8000
```

13项相关软件测试通过；训练与准备过程没有创建机器人动作发布者。

### 2026-10-07：单成功回合过拟合诊断（不部署）

对成功回合 `71960bbce1d24bd9ad9060cb95d0663f` 的171条样本，从当前 BC version295
继续训练；输入、标签和网络架构不变，预训练视觉骨干仍冻结。训练和评价使用同一回合，
不是验证集成绩，不代表真机成功率。

| 模式 | 更新数/学习率 | 本回合归一化 MSE |
|---|---|---|
| 当前部署 BC | 无额外更新 | 0.03472836 |
| 冻结编码器，只训练输出头 | 3000步，1e-4，最佳在2700步 | 0.01654205 |
| 原有可训练编码器部分+输出头 | 1000步，1e-4 | 0.00168793 |
| 在上一结果上降低学习率细调 | 再2000步，1e-5 | 0.00009889 |

最终平移单轴 MAE 为0.00517/0.00383/0.00523mm，旋转单轴 MAE 为
0.00266/0.00318/0.00324度；这只是存储观测上的动作预测误差，不是机器人定位误差。
未发现完全相同的输入对应不同标签；不能据此排除相近观测的动作歧义。
结论：现有架构能很好拟合这一回合；不能直接归因为网络容量不够，也不能证明跨回合表征足够。
冻结特征探针与联合训练的更新预算不同，不能据此作严格容量上限结论。

入口：`python -m omi_hil_rl.hil.overfit_episode`（不导入ROS控制，不启动Learner/Actor真机进程）。
结果分别在 `local/diagnostics/overfit_71960_20261007_01/` 与
`local/diagnostics/overfit_71960_20261007_refine_01/`，含 report、训练历史、逐步预测和诊断权重。
复现第一组需传 `--episode <回合目录> --checkpoint local/bc_episodes/bc_ready_20261007_01/actor.pt
--output <新目录> --updates 1000 --head-updates 3000`；细调传同一episode/checkpoint、新output、
`--updates 2000 --lr 0.00001 --refine-from <第一组目录>/trainable_encoder_and_head_diagnostic.pt`。
权重刻意不兼容部署加载格式；当前部署文件校验未改变。相关BC测试3项通过。

用户随后要求加载测试，已通过显式 `omi_hil_rl.hil.prepare_overfit_eval` 导出独立评估快照：
`local/bc_episodes/overfit_71960_eval_01`，version3295。原始诊断和旧BC不变。
CUDA重载171条预测与保存结果逐项一致（最大差0）；CPU核对最大差0.00555，MSE约0.0001001。
新快照带 `overfit_evaluation.json`，启动会显示 `OVERFIT_EVAL`，不代表泛化已验证。

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/overfit_71960_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

此命令是根据实时观测运行过拟合网络，不是replay标签。先关闭其他动作发布进程，
人工恢复接近示范起点和物体状态，315开始、RB优先、307停止、308成功、Ctrl+C退出。
测试仅一个回合；用户反馈运动与此前有区别，尚无重复试验成功率或成功插入确认。

### 2026-10-07：周期控制验证模式

BC 入口默认 `--control-mode periodic`：目标每 100ms 发布一次，不逐条等待完成回执。
RB 优先；候选缺失、过期或已使用时发送零动作，不重复旧动作。控制端先通过零动作回执
验证 Arm A / base / 10Hz velocity_hold；持续 1s 无回执、明确控制错误或手柄断连仍停止。
这是尽力维持的周期，不是硬实时保证。用户提供过ACTIVE/human/审计落盘现场日志，
但没有硬实时或任务成功率验收；助手没有主动执行真机运动。

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/bc_ready_20261007_01 \
  --resume --control-mode periodic --execute
```

315 开始，RB+摇杆人工控制，308 成功结束，307 提前结束，Ctrl+C 停止并等待写盘。
先结束其他动作发布进程，并在无接触、可安全运动的空间验证。
该模式独立线程保存到 `periodic_episodes/<id>/`，包含逐周期观测、动作、回执与配对检查。
**目前是审计数据，`training_ready=false`，不自动进入旧 RL buffer**；不要将其视作已完成的训练采集链路。
旧同步配对入口可用 `--control-mode receipt`，异步 RL 入口尚未迁移到周期模式。
该 BC 命令不是历史动作 replay；专用入口见下面一节。

### 成功回合动作 replay（不加载网络）

```bash
# 默认仅打印、验证动作，无 ROS 发布者
bash scripts/replay_success_episode.sh \
  --episode local/rl_episodes/test_20261007_161750/episodes/71960bbce1d24bd9ad9060cb95d0663f

# 真机：先结束其他动作发布程序，人工复位并检查物体位置
bash scripts/replay_success_episode.sh \
  --episode local/rl_episodes/test_20261007_161750/episodes/71960bbce1d24bd9ad9060cb95d0663f \
  --output "local/action_replay/test_$(date +%Y%m%d_%H%M%S)" \
  --execute
```

读取 `executed_action`（策略的六维归一化动作），调用同一 `physical_action` 和 policy
发布链路；逐项核对生成的 SDK 指令和原始记录、回执一致。不是模拟手柄，也不是 BC 推理。
默认与 `local/bc_episodes/bc_ready_20261007_01` 的动作/观测契约核对；可指定 `--policy-run`。
315 开始，保留原发送间隔（最终动作仅保持一个名义周期），落后超过50ms停止、不追赶突发发送。
起点要求新鲜末端反馈，距离记录起点不超过10mm、姿态不超过5度；不会自动移动到起点。
这是实验性检查阈值，不保证接触安全；物体、夹持状态还需人工确认一致。
RB 会终止本次序列并允许人工控制，松开不会恢复旧序列；307/308均停止播放。
播放结束后保留人工复位，Ctrl+C退出；再次播放需重新启动命令。
日志明确打印 `RECORDED_ACTION_REPLAY`、源 episode、171条动作、`neural_network=false`。
`commands.jsonl`保存本次发送值，非训练 buffer。开环动作回放不保证重现原来成功结果。
已验证真实记录离线转换；尚未执行真机回放。

### 固定BC公共配置与旧receipt模式

以下说明公共配置；同步WARMUP、异常回合PAUSED及`episodes/ready.json`行为仅适用于
`--control-mode receipt`，不能套用到默认periodic审计模式。

入口 `scripts/run_bc_episodes.sh`，阶段为`BC_EVAL`。
机器人在315开始后使用已训练BC自主执行；不是纯手柄采集。
不启动Learner、不更新权重、不额外添加探索噪声；Critic预训练和SAC+BC训练阶段尚未接入此入口。
新目录独立保存模型快照和回合，旧RL目录不变。

已准备并完成真实BC权重GPU试推理（没有ROS动作发布者）：

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/bc_ready_20261007_01 \
  --resume \
  --execute
```

需先启动外部传感器及支持tagged manual receipts的接收端，关闭旧的SAC/手柄/其他动作发布脚本。
启动显示`FIXED_BC: learner=OFF; deterministic=ON`，策略版本295（BC最佳第5轮的更新计数）。
315开始，松开RB由BC控制，RB按住人工优先，308成功结束，307未成功结束，20秒超时。
回合外RB人工复位，默认314支持自动home；本入口不启用A/B夹爪控制。
Ctrl+C停止输出、排空记录队列、回收推理线程并关闭本次节点；不关闭外部传感器/接收端。
receipt模式异常回合被排除并PAUSED，仍可RB复位，Ctrl+C退出。
periodic模式单回合异常停止并保存审计；加载等外层异常仍可能PAUSED。

新建另一会话（默认模型为`local/rl_training/bc_20261007_20s_01/actor.pt`）：

```bash
bash scripts/run_bc_episodes.sh \
  --output "local/bc_episodes/bc_$(date +%Y%m%d_%H%M%S)" \
  --execute
```

`--prepare-only`只校验/复制模型和试推理，不连接机器人；已存在目录需`--resume`，不覆盖。
恢复时使用会话自己的固定模型快照，不用`--checkpoint`切换；权重哈希变化或混入Learner目录会拒绝运行。
`bc_state.json`记录状态，`bc_session.json`记录来源/哈希；receipt回合保存在`episodes/`，
periodic审计保存在`periodic_episodes/`。人工动作标记human、BC动作标记policy，
只有旧格式完整有效transition回合可后续按既有规则入RL池；periodic审计尚无训练导入器。
不能把BC动作当人工BC标签。
已有模型仍有小旋转误差，软件测试及只读GPU试推理不是自主插接安全验收；现场准备RB接管和急停。

receipt模式若重复显示WAIT_START而从未ACTIVE，查看`summary.json`中的`start_failed`，不是默认归因于315失效。
开始键收到后会打印WARMUP，并每秒打印`WARMUP_STATUS`（缺失输入、历史帧数、候选是否就绪、连接/RB状态）。
观测准备失败打印START_FAILED，原20秒回合预算仍包含准备时间，不自动放宽。
等待观测期间继续处理RB人工复位和314回位；这些准备动作不入训练记录。307/308可取消准备。
当前BC要求`/omi/wrist/color/image_roi`持续出图，不能只检查topic有发布者；也不会用零图替代缺失腕部相机。

## 先做模仿学习的独立基线（2026-10-07）

已训练 `local/rl_training/bc_20261007_20s_01/actor.pt`，不覆盖异步RL目录。
输入、无wrench配置、共享编码器结构及规范化动作标签与当前HIL一致；监督目标是人工实际采用的命令，
不是末端位移差，也不把新采模型动作当人工示范。骨干保持冻结；其余可训练编码器和Actor均值头用MSE训练。
仅从种子索引读取原8个人工回合，沿用6段944条训练、2段352条验证和仅训练集计算的归一化。

复现（目标目录必须新建）：

```bash
bash scripts/train_hil_bc.sh \
  --seed-run local/rl_training/seed_20261007_20s_01 \
  --output local/rl_training/bc_new_01 \
  --epochs 30 --batch-size 16 --patience 8 --device cuda
```

seed=7、学习率1e-4；第13轮结束，验证最佳为第5轮（295次更新），总执行767次更新。
`actor.pt`为验证选择的最佳，`last_actor.pt`为最后一轮，不应混淆。
训练MSE=0.03382，验证MSE=0.07961；验证零动作基线0.11866、训练动作均值基线0.10422。
验证集中|示范dx|>0.05的样本，dx符号一致率86.57%。
验证旋转分量绝对值均值（归一化）约[0.0641,0.0924,0.0842]；
零旋转示范中71.31%仍至少一个预测旋转分量超过0.1归一化量，不能声称已经消除旋转漂移。
验证用于选模型，不是独立测试成功率；样本少且时间相关，不代表真机可靠。

`report.json`、`history.json`及`training_predictions.npz`/`validation_predictions.npz`保存详细对照。
导出的只是确定性BC Actor，Critic未训练、探索方差未校准，没有`learner.pt`。
**不要把它直接替换到旧SAC目录，或把BC目录直接传给`run_async_rl.sh`。**
纯BC评估入口现见上节；BC初始化+Critic预训练流程仍待实现。本次未自动部署真机。

偏移原因排查：当前SAC Actor优化Critic评分+熵项，并无BC监督约束；944条示范仅25条有旋转，
但随机初始化头在整个6维动作范围内学习，缺乏示范覆盖的动作Q值可能外推不准。
这是大旋转的主要嫌疑，不是已证明不存在坐标标定或其他实现问题。
部署过的1038版回合记录显示136条模型动作中134条dx正、整体姿态变化约105度；不是单纯dx反号。

## Actor 内部后台推理（2026-10-07 后续修正）

`--enable-policy` 现在自动启用一个专用推理线程，无需新增参数；需退出旧进程再启动。
ROS接收、手柄和执行仍由主线程管理，等待控制器回执时持续pump并提交最新完整观测。
推理线程仅持有一个运行任务、一个可替换的待处理观测和一个候选，不发布机器人动作。
不把所有历史候选排队；回合内模型固定，换版前关闭旧推理线程。

执行规则：

- 上一条动作仍需回执确认完成，才发送下一条；不是把多个未完成动作叠加下发。
- 交付下一观测时要求其本机参考时间年龄小于50ms，给验证、记录快照和发送前处理留余量。
- 模型控制时，还需该观测的推理候选已就绪；否则继续接收，等待新窗口/候选。
- 发送时仍保留100ms新鲜度、有限动作、传感器有效性与回执检查；没有关闭RGB header检查。
- 记录中的下一观测仍是下一动作的输入；只记录实际采用动作，不将预计算候选充当已执行动作。
- RB接管清除旧候选，等待回执期间发现RB也会请求停止模型动作；人工不等待神经网络推理。
- 若恰在发送前检测到RB释放，旧候选作废；必要时该边界发送并记录人工零动作，再等新候选。
- 回合重置使旧任务结果失效，退出先停止机器人输出，再等待推理线程结束，最后回收Learner。

这是“Actor内部推理与执行等待重叠”，与Actor/Learner两个进程异步是不同层次。
不承诺固定10Hz动作执行：回执过慢或候选未就绪会等下一个观测窗口；不放宽250ms交互等待上限。
异常仍暂停，100ms超时会打印`COMMAND_TIMING_FAILURE`并写`last_command_timing_failure.json`。
其中`inference_wall_ms`在流水线模式下是候选读取耗时，后台真实推理耗时另记为`background_inference_wall_ms`。

验证：模拟125ms动作完成延迟，20步环境交互检查了观测配对、实际动作及发送年龄；
实时传感器+GPU只读测试30秒，模拟125ms回执等待，167次候选交接、0次超100ms，
交接年龄p95=43.97ms、max=49.28ms，后台推理max=16.07ms。
结果文件：`local/rl_training/async_20261007_20s_01/live_pipeline_probe_01.json`。
没有创建机器人动作发布者，也没有同时启动Learner；真机闭环、并发训练下的调度和策略效果仍待验收。

## 一条命令启动哪些部分

同一台电脑、一个终端运行本脚本即可：主进程负责Actor推理、手柄读取和回合采集，
脚本自动启动独立Learner子进程；不需要再手动开训练终端，也不是多机分布式入口。
回合写盘使用独立线程，权重加载/预热使用后台线程。Learner日志写入运行目录 `learner.log`。
摄像头、触觉、机器人状态等传感器服务，以及机器人控制接收端，仍需提前独立启动。
不要同时运行其他手柄控制或模型动作发布脚本。

## 已准备目录与现场命令

### 最新：本次 8 个有效回合（20 秒配置）

使用 `local/rl_episodes/test_20261007_161750` 的8个ready回合；两段discarded排除。
按seed=7分为6段训练944条、2段验证352条，验证数据不入训练池。
独立离线seed为 `local/rl_training/seed_20261007_20s_01`，完成100次CUDA更新；
独立异步目录为 `local/rl_training/async_20261007_20s_01`，并发probe再训练20步至版本120。
回合20秒；无六维wrench输入；replay容量4000条，满后环形覆盖，不是永久示范库。

先启动人工采集与后台训练（不要同时运行独立collect脚本）：

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/async_20261007_20s_01 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 1 \
  --batch-size 2 --publish-every 50 \
  --execute
```

外部传感器及支持tagged manual receipts的接收端需先启动。
315开始、308成功结束、307未成功结束、20秒超时；RB人工控制与回合外复位有效。
Back（默认键码314）可在回合外单按自动回home；A/B（304/305）可在回合内外控制夹爪，
无需按RB。两者沿用人工采集入口的按键边沿和释放后重按规则；Back回位优先于RB摇杆，
通过接收端手动话题发送，不进入RL回放。夹爪操作也不属于当前六维RL动作。

### Back 与夹爪修复后的现场核对

异步入口此前没有把 Back/夹爪控制交给传输层，且 home 指令路由遗漏参数；现已修复。
**先按 Ctrl+C 结束旧进程，待其完全退出后重新运行本节原命令**，旧进程不会自动加载改动。
在 WAIT_START 等回合外阶段短按 Back 检查回 home；ACTIVE 回合内 Back 不执行回位。
短按 A 检查闭合、B 检查张开，两者不要求按 RB；松开按键后再按才会重复触发。
按键日志可用于核对系统是否读到 314/304/305。软件测试已通过，真机动作仍需现场确认；
若按键已记录但设备未动作，保存启动及按键日志以检查接收端或夹爪连接。
修复原因、改动和验证记录见[异步手柄修复日志](../docs/agent/training/chronicles/2026-10-07-async-gamepad-home-gripper-fix.md)。

夹爪默认使用 `gamepad_test.py` 相同的服务器和 `tutorials/gripper_limits.json` 标定；
可用 `--no-gripper` 关闭，或用 `--gripper-*` 参数覆盖。更换手柄可用 `--home-button-code` 指定Back键码。
本机 `local/cuda-env` 已安装夹爪SDK所需的 `grpcio` 和 `protobuf`；重建该环境时需执行
`local/cuda-env/bin/python -m pip install -r local/vendor/optical_module_pu/source/OpticalModule_PU/daimon_stuff/dm_gripper_py/requirement.txt`。
Learner立即满足944条种子数据门槛，不用再等10回合才训练。
每新增10个完整有效回合检查最新有效权重；不是自动挑选best。
Ctrl+C关闭本次采集及Learner，等待保存清理完成；外部设备服务不关闭。
重新启动沿用该命令，不重复初始化目录。

默认松开RB是零动作；显式加 `--enable-policy` 才会在ACTIVE内松开RB执行模型。
当前不建议直接进行自主插接：100步后验证集352条中315条预测dx为负、21条为正，
动作MSE从0.699657降到0.546962仍不代表任务成功。SAC头从头训练，并非已训练BC策略热启动。
batch=2和这次更新数量只用于打通流程，不是已确认有效的学习超参数。

并发测试55次推理：p50=6.33ms、p95=10.76ms、max=11.88ms，无超过100ms；
报告位于新目录 `concurrency_probe.json`。未创建机器人发布者，尚未验证实时ROS闭环或真机成功率。
原始采集和旧15秒会话未改动；后面的15秒命令属于此前测试记录。

### 此前：15 秒配置

已从离线 v2 seed 独立复制：`local/rl_training/async_20261007_01`。
已完成无机器人GPU并发probe，当前权重版本22（训练更新计数，不是效果评级）。
这个模型来自少量更新的流程验证，不是已经学会插 USB 的策略。
启动前保持传感器和支持 tagged manual receipts 的接收端运行，关闭其他动作发布程序。

先验证人工采集与后台训练：

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/async_20261007_01 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 1 \
  --batch-size 2 --publish-every 50 \
  --execute
```

显式允许模型参与时，在同一命令末尾加 `--enable-policy`。
仅 ACTIVE 回合内松开 RB 才执行模型；按住 RB 使用人工动作。默认不加此参数时，松开 RB 为零动作。
新模型效果仍未知，不能把进程跑通当作安全部署验收。开始前确认工作空间、急停和人工接管可用。

- 315：开始回合；不会在程序启动时自动运动。
- 308：成功并结束；307：未成功提前结束；否则按契约时长超时（本目录15秒，含观测预热）。
- 每回合完成独立写盘并提交 ready；接着可以人工复位，再按315开始，不等训练完成。
- 第10、20、30…个完整有效回合结束后检查一次 `actor.pt`。
- 有更新且校验通过：换权重；无更新：沿用旧版；文件或契约不合法：拒绝换版并打印原因。
- 一个回合内版本固定。回合外 RB 人工复位与Back自动回home有效，不进入训练数据；A/B可开合夹爪。
- 重启时先加载最新有效权重，统计已有完整回合，然后重新累计10回合进行下一次检查。

## 两个独立的计数

| 参数 | 含义 |
|---|---|
| `--reload-every-episodes 10` | Actor 每完成10个有效回合，检查/加载新策略 |
| `--publish-every 50` | Learner 每50次Critic更新发布完整权重；不是50个机器人步骤 |
| `--min-online 100` | 在线流至少100条transition才训练，包含已初始化的历史样本 |
| `--min-demo 1` | 人工/示范流至少1条才训练；不是建议只采1条示范 |
| `--batch-size 2` | 小规模验证批量，不是正式学习效果推荐值 |

当前seed的在线与人工流各929条（同组历史人工数据，两路可重叠，不是1858条独立数据），
所以启动后即满足门槛。没有新回合也继续训练旧数据，没有新增数据/更新次数的比例预算。
有限环形池仍可能覆盖历史人工数据；人工流耗尽时Learner等待，不是永久保护示范池的实现。

## 数据与权重如何交换

- Actor：每步快照入有界写盘队列；独立线程压缩/fsync；完整回合生成 `episodes/<id>/ready.json`。
- Learner：只有一个replay写入者，检查ready回合、入池并保存 `imported.json`，避免重复导入。
- 只导入完整回合；当前尚未结束的回合不供Learner训练，避免事后终止标签修改竞态。
- `learner.pt` 保存优化器/RNG等续训状态；`actor.pt` 为推理快照，两者分别原子替换。
- Actor只读取完整 `actor.pt`；后台加载/试推理，校验契约、recipe、归一化、版本递增和有限输出。
- 这里选择的是 **最新有效权重，不是最优权重**：尚无可靠真机评估来决定best，不能以训练loss冒充成功率。
- 每个回合manifest和每条原始记录都保存 `policy_version`；手柄接管仍以实际执行动作为训练标签。
- `async_state.json` 是Actor状态；`status.json` 和 `learner.log` 是Learner进展。

## Ctrl+C 与故障

Ctrl+C首先停止模型/手柄动作输出，保存完整回合；未完成前缀仅审计、不入池。
通知Learner完成当前更新后保存并退出，默认等30秒；超时强制收掉子进程并报告，需要检查恢复状态。
关闭本次手柄读取、记录器、ROS节点及训练子进程，不关闭另外启动的传感器、机器人接收端或RViz。
重复Ctrl+C不打断清理；加载线程仍需结束当前加载操作，因此不是硬实时退出保证。

Learner崩溃或交互记录无效时停止自动采集，PAUSED下保留RB人工复位（前提是ROS/手柄仍健康）。
Ctrl+C退出PAUSED会关闭整个本次会话。零动作请求和接收端deadman不能代替硬件急停。
干净关闭可用原命令重启；dirty replay仍拒绝自动恢复，不要通过删manifest绕过检查。

## 初始化新的独立会话（只需一次）

不要在旧交替训练目录上混跑。使用干净、停止的离线v2 seed：

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/async_new_01 \
  --initialize-from local/rl_training/alternating_20261007_01
```

这会独立复制replay和checkpoint，不修改源数据、不用hardlink共享可写数组。
需要足够磁盘空间；只接受未含在线已提交回合的离线seed。已有目标目录不会覆盖。

## 无机器人并发测试与GPU竞争

```bash
bash scripts/run_async_rl.sh \
  --run local/rl_training/async_20261007_01 \
  --probe-only --probe-updates 20 --batch-size 2 --publish-every 5
```

用已录观测约10Hz推理，同时子进程实际训练，报告 `concurrency_probe.json`。
本次实测：20次后台更新、53次推理，推理p50约5.9ms、p95约10.5ms、最大12.8ms。
**它会更新该目录的模型，但不会创建机器人发布者。** 它不验证实时ROS输入、真实动作或策略质量。
如并行训练影响推理，可减小batch，或通过 `--learner-update-delay 0.05` 让Learner每次更新后让出时间；
也可通过 `--actor-device` / `--learner-device` 分配CPU/GPU。没有保证CPU推理能满足100ms期限。
原100ms命令新鲜度、传感器新鲜度、回执和竞争发布者检查均保留。

本次没有修改奖励与终止契约：307仍为非成功截断，不是新增负奖励失败终止。
