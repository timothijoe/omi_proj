# 2026-10-07：新示范、BC 推理与下一步 RL 交接

## 当前结论

这份记录供下一次讨论 RL 框架时使用。截至 2026-10-07 本次核查，
**新数据已采集并用于 BC，两阶段 BC 模型已训练和准备真机评估；尚未用它建立新 RL 会话，
也没有新模型的真机成功率结论。**旧的
`local/rl_training/bc_protected_dual_20261007_01` 仍以早先 8 回合、BC version11795
初始化，不能当作这批新模型的 RL 会话。

| 环节 | 当前产物 / 状态 |
| --- | --- |
| 人工采集源 | `local/rl_episodes/demo_new_20261007_213643/`；10 个源回合，9 个按成功结束、1 个超时 |
| 周期审计 | `periodic_episodes/` 保存原始审计；11 个 `episodes/*/ready.json` 连续片段，共 1387 条有效人工动作 |
| BC 专用索引 | `local/rl_training/bc_index_demo_new_20261007_213643/dataset.json`；按源回合分组，样本哈希已核对 |
| 本次训练实际索引 | `local/rl_training/bc_seed_demo_new_20261007_213643_v3/dataset.json`；与 BC 专用索引的片段及 1387 个样本哈希一致 |
| 两阶段 BC | `local/rl_training/bc_demo_new_20261007_213643_coarse_fine_01/actor.pt`；从 version295 出发，训练 4000+8000 步，选中 version12045 |
| BC 真机评估快照 | `local/bc_episodes/demo_new_20261007_213643_eval_01/`；固定 version12045，Learner 关闭 |
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

本次核查时该评估进程已退出，`bc_state.json` 为 `CLOSED`、version12045、
`learner_enabled=false`、`error=null`。评估目录现有 3 个完整周期审计，均为
200 tick 到时、`success=false`；各自 `matched_pairs` 为 181、163、177。
BC 评估入口是 audit-only，故 `training_ready=false`、没有导出的训练 `ready.json`；
这不表示三次推理没有发送动作，也不能仅凭日志判断真实任务是否成功。
`complete_episodes=0` 是此入口的提交计数，不能替代上述 3 个审计回合数。
本次文档工作没有停止进程或控制机械臂。下一次启动任何 RL Actor 前仍要重新确认
没有其他动作发布者，避免并行控制。

## 接入 RL 前的明确边界

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
再决定如何建立新 RL 种子和是否让策略输出参与真机回合。此记录不启动 RL。
