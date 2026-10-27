> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-runnable-baseline.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/online-rl.md)；本页保留原过程与证据。

# 2026-10-11：在线HIL RL可运行基线

用户确认：这一版至少已经是可以运行的版本，先记录作为后续迭代基线。
本记录定位为**采集、存储、回放、训练、策略更新和监控已实际联通的可运行基线**，
不表示策略效果最优、全程自主成功率已验证，或所有现场异常已解决。
本次仅整理文档，没有修改训练参数、模型、数据或运行中的进程。

## 代码与现场定位

- 记录时间：**2026-10-11 20:34:09，Asia/Shanghai**。
- 分支：`oct_10_branch`。
- 当时HEAD：`e57bd5e04c6db88c76b5d4ea9842f43badd5359a`；读取时工作区干净，此后本轮新增的是文档。
- 活动会话：`local/rl_training/bc12045_newdata_30s_20261011_01/`。
- 原BC checkpoint：`local/bc_episodes/demo_new_20261007_213643_eval_01/actor.pt`，BC12045。
- 原BC SHA-256：`47838ba160722c3096e98c5e39cfc3a71b2ea1d786470f93662b4c6dc0eb053f`，此前两次重置均核对未变。
- 监控网页：http://127.0.0.1:8771/ 。

活动目录名称中的30s是历史命名，当前实际时限为45秒。代码commit可定位这版实现；
活动会话的checkpoint和数据仍在变化，本记录不是模型/数据的不可变备份，也没有创建release/tag。

## 已跑通的能力

1. **原BC初始化、只用本批新数据**：weights-only继承原BC的参数和归一化，旧Demo及旧在线经历不导入。
   本次有效采集从空Demo/RL开始，人工接管形成新Demo；BC参考模型保留原BC权重。
2. **在线采集与人工接管**：Start开始回合，RB＋摇杆接管，308成功，307提前结束；after-inference仲裁。
   夹爪按用户要求保持既定闭合状态，`--no-gripper`禁用A/B控制。
3. **单帧存储与历史重建**：原始图像/触觉/状态按单帧保存，窗口引用重建十帧历史；
   初始窗口保留可用历史。原始回合、异常和回执保留审计文件。
4. **Demo/RL双池**：全量有效数据留盘、SQLite登记来源，训练从完整transition内存缓存抽样；
   人工样本可同时属于两池，共享一份数据，池成员滚动独立，历史数据可从磁盘换回。
5. **后台Learner**：batch64实际训练，Critic预热、SAC+BC更新、保存与续训均已运行；
   更新预算用完等待新数据，不因Actor等待Start就无限训练。
6. **在线探索**：策略动作加入std0.05、clip0.15的归一化高斯噪声，最终动作限幅[-1,1]；
   人工、握手及复位不加噪声。已从真实NPZ核对非零噪声和实际动作标签一致。
7. **权重交接**：Learner定期发布，Actor在回合边界检查并加载；已实际从0更新到1250、1784及后续6950。
   正常Ctrl+C保存退出，同一目录重启恢复checkpoint、优化器及数据，启动即加载最新策略。
8. **网页监控**：显示Actor已加载/最近发布/训练版本，Demo/RL内存与磁盘存量、共享内存预算、
   成功/未成功/timeout/人工提前结束/异常/暂存分类，点击统计筛选并逐帧审阅。
9. **问题数据重置**：支持先完整归档旧会话、核验哈希，再原路径重建空池与原BC初始化；
   同步更新config、模型、session及replay契约，避免只改timeout造成契约不一致。

## 当前配置基线

| 配置 | 值 |
| --- | --- |
| 每回合时限 / 目标观测频率 | 45秒 / 10Hz |
| 训练数据 | 仅本会话重建后新采集，固定历史seed=0 |
| batch size | 64 |
| 正常Critic批次 | Demo/RL各半；BC约束另采新人工Demo |
| 启动门槛 | min-online=100、min-demo=100 |
| Critic预热 | 1000次，使用新Demo |
| gamma / tau | 0.98 / 0.005 |
| 编码器 | 整体冻结，包括触觉CNN与融合层 |
| Critic / Actor学习率 | 3e-4 / 1e-5 |
| Critic:Actor更新比例 / BC权重 | 2:1 / 10 |
| 奖励 | 合格成功末条transition为+1；普通动作0；成功终止关闭bootstrap |
| 探索 | 策略动作std0.05，噪声每轴clip0.15，归一化tanh之后加入 |
| 驻留目标 / 受管管线预算 | 16 GiB / 20 GiB，不是整个进程RSS或显存上限 |
| Learner发布 / Actor检查 | 每50次Critic更新 / 每新增10个有效回合 |
| 累计更新预算 | 1000 + 已登记online transition数 × 1 |

## 20:34现场快照

运行中的多个文件分开读取，数字可能相差一个更新周期；以下是带时间戳的观测，不是最终统计。

- Actor：ACTIVE，已加载版本 **6950**，完成有效回合55，最近检查基点53，检查间隔10。
- Learner：TRAINING，batch64，更新 **7330**，最近发布 **7300**，本进程Actor更新2773次；
  累计更新预算20882，当前没有等待原因。
- 原始回合：共58个目录，其中57个已结束、1个进行中/暂存。
- 已结束结果：成功28、timeout25、人工提前结束2、异常2；未成功合计29。
- 两次异常分别为 `receiver fault: sdk_rejected` 和
  `receiver receipt link silent for 1s; stopped (not a per-command wait)`。
- 人工标记成功占已结束回合约49.12%；其中可能存在人工接管，不能解释成自主策略成功率。
- 磁盘目录：RL19882条，新人工Demo5591条，历史固定seed0。
- 内存可采样成员：Demo3769、RL3963；独立驻留记录7539，两池存在共享，不能直接相加。
- 受管管线内存峰值17,791,032,348字节，约16.57 GiB；后台加载错误为null。

## 当前续跑命令

仅在上一套在线进程正常退出后执行，继续同一目录；不重新初始化或清空数据。
相机、触觉和机器人接收端沿用现场配置。

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 64 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

监控服务已运行时直接打开网页；需要重启监控时，另开终端执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 --port 8771
```

另建一批同配置数据时，用新目录执行 `prepare_bc_rl.sh`，指定原BC来源、
`--weights-only --episode-seconds 45 --replay-backend cached`，不传历史recorded-source；
现有会话不要再初始化。新池必须重新采集有效人工接管数据，满足Demo门槛后才开始学习。

## 已知问题与后续待办

- **触觉编码器可训练**：用户已确认需要改进；当前仍冻结。需明确只解冻触觉还是包含融合层，
  以及预热切换、共享优化器归属和checkpoint恢复方式。
- **长回合gamma衰减**：当前0.98，终点+1跨300步仅剩约0.002333；
  更大gamma及成功信号传播方案仅记录候选，尚未修改。
- **Critic价值校准与成功监督稀疏**：先前离线实验出现负Q，延长预热并未完全解决；
  在线成功计数和loss下降不能代替独立任务效果评估。
- **现场回执/SDK异常**：仍有上述两类异常，需要分别追查；原始数据保留、异常回合不作为训练transition入池。
- **batch64容量与并发**：64已实际运行，但用户取消了专项容量对照；未完成64/128峰值显存、
  吞吐和Actor延迟的系统比较，不把“能运行”写成“最优或长期无异常”。

以上待办遵照用户要求先记录，本次没有实施变更。后续以单因素实验迭代并保留本基线定位。

## 详细证据索引

- [双池实现与独立淘汰验证](../../../../replay/records/training/chronicles/2026-10-10-cached-dual-replay.md)
- [只继承BC权重、数据全部新采集](2026-10-11-weights-only-new-data.md)
- [会话时限与可视化](../../../../visualization/records/training/chronicles/2026-10-11-30s-buffer-dashboard.md)
- [两次问题数据归档、最新45秒重建](../../../../replay/records/training/chronicles/2026-10-11-invalid-data-reset.md)
- [batch64与实际探索记录](2026-10-11-batch64-exploration-live.md)
- [触觉与gamma待改项](../../../../sensors/records/training/chronicles/2026-10-11-tactile-gamma-pending.md)
- [Critic负Q离线对照](2026-10-11-critic-diagnostics.md)

已有专项记录包含软件回归、真实数据/模型验证和网页检查；本次只是文档归纳，没有重复执行训练测试。
