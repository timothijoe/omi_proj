# 2026-10-07：新示范、BC 推理与下一步 RL 交接

> 本页前半记录 10 月 7 日准备和评估阶段；10 月 8 日新 RL 已完成首批真机运行。
> 最新数据、Learner 状态和 EEF 时间戳分析见[后续编年](2026-10-08-first-online-rl-run.md)。

## 当前结论

这份记录供下一次讨论 RL 框架时使用。截至 2026-10-07 本次核查，
**新数据已采集并用于 BC，两阶段 BC 模型已训练和准备真机评估；尚未用它建立新 RL 会话，
也没有新模型的真机成功率结论。**用户决定暂缓触觉预警和保护，先整理文档，之后再讨论真机 RL。
旧的
`local/rl_training/bc_protected_dual_20261007_01` 仍以早先 8 回合、BC version11795
初始化，不能当作这批新模型的 RL 会话。

| 环节 | 当前产物 / 状态 |
| --- | --- |
| 人工采集源 | `local/rl_episodes/demo_new_20261007_213643/`；10 个源回合，9 个按成功结束、1 个超时 |
| 周期审计 | `periodic_episodes/` 保存原始审计；11 个 `episodes/*/ready.json` 连续片段，共 1387 条有效人工动作 |
| BC 专用索引 | `local/rl_training/bc_index_demo_new_20261007_213643/dataset.json`；按源回合分组，样本哈希已核对 |
| 本次训练实际索引 | `local/rl_training/bc_seed_demo_new_20261007_213643_v3/dataset.json`；与 BC 专用索引的片段及 1387 个样本哈希一致 |
| 两阶段 BC | `local/rl_training/bc_demo_new_20261007_213643_coarse_fine_01/actor.pt`；从 version295 出发，训练 4000+8000 步，选中 version12045 |
| BC 真机评估快照 | `local/bc_episodes/demo_new_20261007_213643_eval_01/`；固定 version12045，Learner 关闭；目前 12 个周期审计 |
| 新双池 RL | 尚未准备，也未把新示范导入旧池 |

训练集归一化动作 MSE 从旧 BC 在新数据上的 0.650336 降到 0.004515；
最佳权重来自第 11750 次新增更新，而非最后一步。全部 1387 条都参与拟合，
**没有独立验证集**；MSE 不能当成真机成功率。冻结视觉骨干逐张量未变，模型重载预测差为 0。
训练详情见[新周期数据 BC 记录](2026-10-07-new-periodic-human-bc.md)，
采集按键、日志和原始数据语义见[人工周期采集记录](2026-10-07-human-periodic-collection.md)。

## 固定 BC 的真机推理

当前评估目录的 `bc_session.json` 指向上述新模型，`policy_version=12045`，
`learner_enabled=false`。这是实时传感器输入下的网络推理，不是训练动作回放，也不会更新权重。
在项目根目录运行一个回合：

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

脚本使用局域网 ROS 发现来读取外部 RGB。315 开始；按住 RB（311）时人工接管；
308 标记成功、307 提前结束，20 秒到时则记非成功。日志应显示
`FIXED_BC`、`OVERFIT_EVAL` 和 version12045。退出后可查看该评估目录的审计，
再判断模型是否值得作为下一阶段 RL 起点。

周期评估另有彩色中文横幅提示等待 Start、进入 ACTIVE、任务成功或未成功，
以及评估审计保存后的指令和配对次数；原有英文状态 JSON、`PERIODIC` 和
`PERIODIC_SAVED` 日志保留。终端输出有颜色，重定向输出或设置 `NO_COLOR`
时为无色文字。这里的“评估审计已保存”不表示已进入训练池。

### 触觉预警与接收端保护：目前均不启用

普通 BC 推理命令**默认不启动触觉差值预警**；接收端
`tactile_guard_enabled` 最近一次只读查询为 `false`，因此模型动作也不受该保护拦截。
RL 的 `AsyncActor` 不装载 BC 的 wrench 监测器，`run_async_rl.sh` 也没有自动启用它；
接收端的触觉保护由接收端启动参数控制，默认 `false`，BC/RL 都须由操作者
**显式将 `tactile_guard_enabled:=true` 加到接收端启动命令**才会触觉拦截模型动作。
用户当前选择先不启用两者。以后若要在 BC 周期评估里单独开启**只读预警**，需显式添加
`--wrench-warning`；它不会开启接收端保护。示例（仅供以后使用）：

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute \
  --wrench-warning --wrench-force-xy-warning 4.0 --wrench-torque-warning 1.2
```

这个可选监测订阅双指 wrench 作**只读逐回合预警**。操作员应在未接触接口、
夹持稳定时按 Start；程序取按键前 1 秒每指至少 20 条、覆盖至少 0.4 秒的新鲜样本的六维中位数作基线，
并检查三维力最大偏离不超过 0.5、力矩最大偏离不超过 0.15；任一指整段六维全零也拒绝。
缺数据或波动过大时打印
`BC_WRENCH_BASELINE` 的不可用原因，本回合不作阈值判断。基线成功后比较每指
`sqrt(ΔFx²+ΔFy²)` 和 `sqrt(ΔTx²+ΔTy²+ΔTz²)`，三个力矩分量都分别减基线；
代码默认 1.5 / 0.4 是早期**预警候选值**，用户最近试看的临时参数改为 4.0 / 1.2，
只通过命令行参数使用，尚未改为代码默认值或保护阈值。
可用 `--wrench-force-xy-warning`、`--wrench-torque-warning` 调整。超限打印
`BC_WRENCH_WARNING` 和黄色中文提示，每指最多每秒一次；每回合的基线、峰值和超限
样本计数保存在 `periodic_episodes/<episode>/wrench_monitor.json`。回合中收到六维全零
样本会计入 `invalid_samples`，不当作真实差值超限。该监测不改变模型动作、
回合成功标签或接收端保护开关；接收端原有一次性锁定保护仍独立。
这些 SDK 数值未标定，需用有正常／异常接触标记的数据定最终阈值。
若以后只想调试阈值而不运行 BC 或机器人动作，可单独运行：

```bash
bash scripts/watch_bc_wrench.sh \
  --wrench-force-xy-warning 4.0 --wrench-torque-warning 1.2
```

该入口同样用手柄 Start(315) 建立双指基线，
每秒打印 `BC_WRENCH_LIVE`，详见[只读触觉预警教程](../../../../tutorials/tactile_warning.md)。

本次核查时该评估进程已退出，`bc_state.json` 为 `CLOSED`、version12045、
`learner_enabled=false`、`error=null`。评估目录现有 12 个周期审计：11 个达到
200 tick 后超时、1 个因接收端回执链路静默 1 秒而在 10 tick 停止；全部
`success=false`。这些记录不能据此计算任务真实成功率，用户曾反馈部分动作效果不如之前，
原因尚未由可复现实验确认。
BC 评估入口是 audit-only，故 `training_ready=false`、没有导出的训练 `ready.json`；
这不表示推理没有发送动作，也不能仅凭日志判断真实任务是否成功。
`complete_episodes=0` 是此入口的提交计数，不能替代上述 12 个审计回合数。
本次文档工作没有停止进程或控制机械臂。下一次启动任何 RL Actor 前仍要重新确认
没有其他动作发布者，避免并行控制。

## 接入 RL 前的明确边界（准备前记录）

1. 当前 `scripts/prepare_bc_rl.sh` 会读取 BC 目录的训练索引，并调用旧同步命令的
   通用校验器。新片段的 `command_status=periodic_accepted_command` 会被它拒绝；
   **因此现在不要直接把新 BC 评估目录传给该脚本并期待得到可运行的新 RL 会话。**
   需要单独设计和核对周期示范到 RL 初始种子池的准备路径，保留动作来源、回执证据、
   时序、奖励和截断标签，且不能把“接收命令”写成“已测得位移”。
2. 用户明确要求周期格式的新增校验只用于模仿学习。现有代码将这项校验限定在
   `hil/periodic_bc_label.py`、BC 读取器和 BC 专用索引；通用
   `demo.validate_command_label`、`TransitionReplay` 和 RL 控制规则未改。
   后续 RL 接入应先明确其独立适配边界，不静默放宽通用框架限制。
3. 旧双池的固定初始示范为早先 1296 条，新批次 1387 条并未替换它。
   新 RL 应使用独立目录，并核对 BC Actor、Encoder/归一化、示范索引及 Critic 初始化
   来自同一明确版本；不要覆盖或继续旧会话来冒充新热启动。
4. RL 的周期控制、异步 Learner、双池采样和每 10 个完整有效回合检查新策略，
   已有[旧模型运行教程](../../../../tutorials/async_rl.md)和
   [双池开发记录](2026-10-07-dual-replay.md)。这些是框架实现和旧目录验证，
   **不是新 BC version12045 的端到端真机验收**。先依据 BC 实际推理日志检查运动、
   成功判定及数据质量，再决定新 RL 的准备和现场测试顺序。

下一步讨论时，先读取本页和新 BC 的 `report.json`、评估目录的最新回合审计，
再决定如何建立新 RL 种子和是否让策略输出参与真机回合。触觉预警和接收端保护先保持
关闭，待正常／异常接触区间标注、阈值和动作含义确定后再议。此记录不启动 RL。

## 后续进展：新 BC 已建立独立 RL 会话

`prepare_bc_rl.py` 的**BC 训练索引导入**现在使用已有的 `validate_bc_label`：
对周期人工标签核对原始命令、接收回执与因果观测，再写入固定初始示范池。
这只改了示范导入边界；通用 `TransitionReplay`、`demo.validate_command_label`
与在线 RL 控制规则未改，也没有把命令接受改写成实测位移。

新种子 `local/rl_training/bc_demo_new_20261007_213643_rl_seed_01` 完成 11 段、
1387 条示范导入；初始 Actor 与 BC12045 全参数一致，Critic/target 新建，
编码器冻结，前 1000 次更新只训练 Critic，之后 Actor 学习率 1e-5、BC 项权重 10。
`rl_probe_01` 为独立并发检查副本：20 次 Critic 更新并发 55 次录制观测推理，
最长 11.52 ms、超 100 ms 0 次，未创建机器人命令发布者。`rl_live_01`
为另一个未启动的真机会话副本，不能用 probe 目录代替。

接收端只读核查确认策略 `/omi/action/decision` 与人工
`/omi/controller_test/decision` 都有接收端订阅、检查时均无发布者；
接收端连接及运动授权参数有效，`tactile_guard_enabled=false`。
8 秒现场传感器只读推理检查得到 62 次候选、0 次超过 100 ms，所需传感器均有消息。
这些检查尚未验证真实接收端回执、机械臂运动或策略任务成功。
新 BC 既有 12 个评估审计没有成功标记；首次 RL 运行需在操作者可接管时观察运动与回执。
实际命令及状态解释见[异步真机 RL 教程](../../../../tutorials/async_rl.md)。
