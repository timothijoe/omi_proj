# 2026-10-07：独立示范/在线双池与固定初始示范

## 需求与范围

用户要求将原来单物理环形池＋human/online标签，改成独立管理容量的示范池和在线池。
本次只修改存储、采样、Learner启动门槛和迁移入口，未改变动作表示、手柄按键或真机控制路径。
HIL-SERL参考的50/50混合与人工干预双写被保留；固定初始示范区是本项目额外保护，不宣称官方自动永久保留。

## 已实现

- `training/dual_replay.py`：`DualTransitionReplay`复用磁盘transition格式，逻辑demo池由
  `demo/initial`（封存、满了拒绝写）及`demo/interventions`（独立环形）组成，`online`为另一独立环形池。
- 初始人工示范只放固定区；在线人工动作同时写入干预区与在线池，模型动作只写在线池。
  是否成功不决定在线入池；沿用上游有效性检查与原奖励/终止标签。
- 正常RL batch必须为偶数且>=2，严格50%示范＋50%在线；各池均匀、有放回随机采样。
  demo内部按保留样本数自然加权，在固定区与干预区的并集均匀采样。
- BC额外约束只从demo取human标签；没有自动示范质量审核，也不把失败回合改成成功。
- 三个存储分区容量互不占用，在线或干预区回绕不会覆盖初始示范。目录和容量见[教程](../../../../tutorials/async_rl.md)。
- 顶层写者锁防并发修改；写前将顶层manifest标为dirty，所有分区持久化成功后才标clean。
  部分跨池写失败后close不将它伪装成干净状态，重开明确拒绝。
- `import_ready`按backend分派。成功checkpoint后、imported标记之前中断，可凭顶层last_import补记，
  不重复双写。硬崩溃脏池仍需恢复干净备份，未实现任意时点自动崩溃修复。
- `open_replay`同时支持旧单池与新双池，不静默迁移旧数据。

## 初始示范不再冒充新增在线经验

新双池会话的历史1296条只计demo，online初始为0。为使BC保护式初始化仍能工作：

1. 编码器冻结且处于Critic预热预算内时，可以用demo-only batch预热，Actor/温度仍不更新。
2. 预热完成后，要求demo与online均非空并达到用户门槛，默认online至少100条有效transition。
3. 正常更新按严格50/50执行，不悄悄回退为仅示范训练。

日志增加`demo_only_warmup`，等待状态增加`waiting_for_online`和`critic_warmup_remaining`。
等待Learner不阻塞Actor采集；在线门槛100条transition与10个回合检查checkpoint是两件事。
仍未实现更新次数随新增样本量递增的预算，在线门槛达标后Learner仍可反复训练现有数据。

## 新建与旧数据迁移

`scripts/prepare_bc_rl.sh`现在默认建立双池，新增`--intervention-capacity`（默认2000）；
`--capacity`指定online容量（默认4000），fixed区容量按初始训练样本数分配。

`scripts/migrate_dual_replay.sh --source OLD --run NEW`只允许独立新目标目录，锁定源会话Actor/Learner，
要求源单池clean且无未完成导入。验证原始训练索引/逐条哈希及人工动作标签，从原始文件恢复固定示范；
旧池当前保留的非种子online按环形时间顺序迁移，人工部分同步进入干预区。
Critic、Actor、target、优化器、计数等checkpoint原样复制；回合与导入标记复制，避免重复导入。
丢失的原始种子文件、未知离线示范来源或不一致checkpoint拒绝迁移，不猜测标签。
源文件与旧会话保留；不能恢复已被旧池覆盖、且未在本次迁移来源中的非种子online数据。
异步seed克隆也保留`control_mode`及replay配置，避免克隆后误回到旧同步控制路径。

已从`local/rl_training/bc_protected_20261007_01`迁移到
`local/rl_training/bc_protected_dual_20261007_01`：

| 项目 | 数量 |
|---|---:|
| 固定初始人工transition | 1296 |
| 从online分类中移除的历史种子 | 1296 |
| 实际新online经验 | 0 |
| 在线人工干预 | 0 |
| online容量 | 4000 |
| 干预区容量 | 2000 |

1296条来自8回合（含2个超时回合），不是宣称全部成功。
迁移后的`dual_migration.json`记录来源与计数；`bc_initialization.json`是原热启动历史报告，当前计数以
顶层replay manifest和Learner `status.json`为准。

## 验证证据与边界

- 新增`tests/test_dual_replay.py`：容量回绕不覆盖种子、人工双写、严格50/50、BC采样排除模型、
  空池拒绝隐式回退、重开/写锁、半次跨池写故障、导入补记不重复、预热后等在线数据、迁移权重保留。
- 扩展到磁盘/transition/双流/异步等相关回归：84通过、2跳过（CUDA相关在普通沙箱跳过）。
- 真GPU离线并发probe：新目录版本4→8，追加4步demo-only Critic预热，46次推理，
  p95=11.03ms、max=13.09ms、超过100ms为0；BC参考漂移为0，机器人动作发布者为0。
- 最后再次逐项比较：双池目录RL version8全部Actor张量与BC11795相等。
- 未启动真机采集；现场数据有效率、成功奖励保留率及RL策略效果仍需验证。
- 不包含Encoder解冻、随机探索、自动策略回退或训练UTD预算；这些仍是独立待办。

## 本轮交接：重新采集示范，再启动BC→RL

用户决定重新采集一批人工示范，继续标注成功、提前结束和超时，再以新BC作为在线RL起点。
这是下一阶段计划；上面的1296条种子、BC11795与双池version8仍来自此前8回合，
不是新采集数据训练的结果。本次没有用新数据训练BC，也没有将其自动导入已有双池。

纯人工采集入口仍为`collect_rl_episodes.sh`，不加载模型、不启动Learner。
该入口仍走回执确认的同步transition采集；不能把它与保护式RL的periodic后台校验路径视为完全相同。
有效人工数据可以作为BC动作监督和RL示范，但需先审核动作、观测及标签；
失败/超时保留原标签，不能为了作demo而改成成功，也不代表所有人工动作都适合BC。
操作命令见[新示范采集教程](../../../../tutorials/rl_episode_collection.md#新一批示范采集2026-10-07)。

### 最近现场现象（暂缓排查，不作为已修复项）

用户运行20秒人工采集，目录`local/rl_episodes/demo_new_20261007_203257`。
已读取`summary.json`，结果为：

| 回合ID | 记录条数 | keep | 结束原因 |
| --- | ---: | --- | --- |
| `5ca96b9fd9794319a6a94e6e52f6be46` | 0 | false | 接收端拒绝/修改命令或坐标契约不一致 |
| `73a3a4ddd0eb4bdc9f21599ba92e194d` | 64 | true | `manual_stop`，非成功 |
| `b28196d744be481d8ad304de934a9d74` | 20 | false | 接收端拒绝/修改命令或坐标契约不一致 |

终端记录显示RB、315、307和Back被识别，观测预热可完成。
上述通用错误不足以确认是包络限制，也不能排除其他接收端拒绝原因。
用户提出可能是包络问题并决定暂时保持现状：未据此修改包络、放宽保护或发送测试动作。
两个`keep=false`回合不能进入训练池；64条保留数据仍需核实实际运动和示范质量，
`keep=true`不等于已经证明机器人按预期运动。此处仅记录证据，不继续排查。

下一步待用户确认：验收遥操作→完成新示范采集和审核→新目录训练BC→离线/真机评估BC→
以新BC与对应示范新建双池RL会话。不要覆盖现有模型或把旧会话当作新数据训练结果。
