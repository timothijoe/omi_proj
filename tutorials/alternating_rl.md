# 按回合交替的真机 RL（2026-10-07 最小版本）

入口：`scripts/run_alternating_rl.sh`。先离线准备 v2 模型和 replay，然后启动现场回合。
本版本不是效果验收：新 SAC 控制头从头训练，不能保证已学会插入或方向正确。
默认现场只由人工操作，但每回合结束都会真实训练、保存并加载新策略。

已准备目录：`local/rl_training/alternating_20261007_01`，可以直接从第 2 步开始。
本次仅以 batch=2 完成 2 次 GPU 更新，重载误差为 0；这是流程测试模型，不是可用插入策略。
留出集 222 条预测 dx 全为负，动作 MSE 未改善。因此今天先用默认人工模式，
不要因为流程跑通就开启该模型自主插入。初次现场训练可用 `--batch-size 2` 复用已验证配置。

## 1. 一次性准备（不控制机器人）

在项目根目录执行；`--run` 必须使用新目录。旧 v1 / BC checkpoint 不能直接替代此步骤。

```bash
bash scripts/run_alternating_rl.sh \
  --run local/rl_training/alternating_20261007_01 \
  --prepare \
  --source local/rl_episodes/collect_20261006_001958 \
  --updates 10 --batch-size 32 --capacity 2000
```

默认 CUDA，骨干权重 `local/pretrained/serl_resnet10/backbone.pt`。
准备会检查历史回合、按回合留出验证集、仅以训练集计算归一化，再做真实 SAC 更新。
容量是 transition 数；必须大于初始训练集，脚本检查磁盘空间。
若显存不足，用 `--batch-size 8`；CPU 可以用 `--device cpu` 做软件验证，
不保证满足真机策略的 100 ms 新鲜度要求。

## 2. 先验证人工回合 + 自动训练

保持传感器与接收端运行，关闭其他手柄/策略发布程序。接收端须支持 tagged manual receipts。

```bash
bash scripts/run_alternating_rl.sh \
  --run local/rl_training/alternating_20261007_01 \
  --updates 10 --batch-size 32 --execute
```

- 315：开始新回合。启动程序不会自动运动，按键须先释放再按。
- RB + 摇杆：人工动作。默认模式松开 RB 为零动作。
- 308：成功并结束，奖励 1。
- 307：提前结束，奖励 0；与成功同时触发时，提前结束优先。
- 到时：超时结束，奖励 0。时长继承准备数据的契约，示例数据是 15 秒，包含历史观测预热。
- 有效成功/提前结束/超时回合自动保留；观测、回执、写盘等异常回合不入池。

流程日志：`WAIT_START → ACTIVE → SAVING → TRAINING → LOADING → WAIT_START`。
保存和训练期间，先释放再按 RB 可以人工复位；这些动作不进入 replay。
此时按 315 不排队；显示 `WAIT_START` 后重新释放并按下才开始下一回合。
训练详细输出在同目录 `learner.log`，避免刷屏掩盖按钮/状态日志。

## 3. 显式允许模型参与

后续策略经过离线检查、确认现场安全条件后，停止旧进程，使用同一目录。
以下是功能用法，不是建议部署本次仅更新两步的模型：

```bash
bash scripts/run_alternating_rl.sh \
  --run local/rl_training/alternating_20261007_01 \
  --updates 10 --batch-size 32 --execute --enable-policy
```

仅 ACTIVE 回合内松开 RB 才执行模型；按住 RB 接管。模型采用确定性均值动作。
训练/加载期间没有模型动作。策略整个回合固定，每次训练成功后才换版本。
人工走接收端配置的 manual topic，模型走 `/omi/action/decision`；实际 topic 写入 command audit。
仍保留原观测、100 ms 命令新鲜度、回执和竞争发布者检查，没有为了跑通关闭这些检查。
本入口没有接入 BC 推理脚本的 314 自动回 home 功能；复位使用 RB 人工控制。

## 4. 保存、退出和限制

- Ctrl+C：先停止动作；完整回合保留，未完成前缀仅审计、不入池。重复 Ctrl+C 不打断保存。
- 训练中 Ctrl+C：向独立 learner 发 SIGINT，等待完整更新后保存；最长等 30 秒。
  超时会强制结束，需检查 checkpoint/replay，不能假定完整恢复。
- 正常回合边界退出可以同命令重新启动；不会自动继续机器人运动。
- 训练/加载出错时进入 PAUSED，不自动开始下一回合；进程存活期间 RB 可复位。
  若手柄/ROS/竞争发布者本身异常，人工复位也可能不可用，需现场急停/排查。
- `alternating_state.json` 保存阶段与目标版本；`tasks/<episode>.json` 是完成确认。
  未确认训练任务、已保存但无任务结果的回合会拒绝自动恢复，首版需人工检查；不要删除状态强行继续。
- `episodes/<id>/` 保存原始回合，`ready.json` 表示完整可入池，`imported.json` 表示已入池。
  `replay/` 是磁盘训练池，`learner.pt` 是可续训状态，`actor.pt` 是推理权重。
- replay 为有限环形池，旧人工样本可能被覆盖；若 demonstration 流耗尽，训练等待后超时暂停。
  今日短程验证需保留足够人工交互，不是无限长期无人值守方案。
- 不要另开 learner 或离线训练修改同一个运行目录。在线 learner 限于当前调度任务。
- 停止发布/零动作是停止请求，不等于硬件位置静止的独立认证。

此版本复用现有 RL 的动作契约；不代表其他 agent 所说的动作统一或物理坐标标定已验收。
默认不加入六维力/力矩作为网络输入，也没有新增自动成功识别、自动物体复位或触觉保护开关。
