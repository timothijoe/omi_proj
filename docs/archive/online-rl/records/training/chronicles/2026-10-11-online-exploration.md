> 历史资料：原路径 `docs/agent/training/chronicles/2026-10-11-online-exploration.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/online-rl.md)；本页保留原过程与证据。

# 2026-10-11：在线策略探索与Actor换权重

后续已完成[batch64在线训练与实际噪声记录核验](2026-10-11-batch64-exploration-live.md)。
下文的4777会话、batch2命令及当时未上机的结论为早期记录；最新活动会话、45秒配置和batch64命令见后续记录。

用户要求给在线RL加入探索，并确认Learner何时把新checkpoint交给Actor。
本次增加可显式开启的受限高斯动作噪声，未启动或重启机器人进程。

## 探索行为

`run_async_rl.sh` 新增 `--exploration-noise-std`（默认0，关闭）和
`--exploration-noise-clip`（默认0.15，每轴噪声绝对上限）。参数均为归一化动作单位。
命令示例使用std=0.05、clip=0.15，作为待现场验证的起始设置，不表示已验证最优。

具体为 `action = clip(mean_action + clip(N(0, std²), -clip, clip), -1, 1)`。
mean_action是原来的 `tanh(mean)`；六轴分别独立采样，噪声加在tanh之后。
这属于额外行为探索，不是直接启用SAC学习出的标准差，也不改变Learner的损失或随机采样方式。
按当前会话的动作尺度，std=0.05对应每轴约0.0289 mm / 0.0289度；噪声上限对应约0.0866 mm / 0.0866度，
均指单条动作的命令增量，不等于实际末端位移，最终动作饱和还会减小实际扰动。

- 只在策略候选通过仲裁、准备发出时抽取噪声；推理线程仍计算确定性候选。
- RB人工动作、握手零动作、没有新候选、回合外复位不添加噪声；不改变夹爪行为。
- after-inference与immediate两个周期仲裁模式均接入；旧receipt会话拒绝开启，避免参数静默无效。
- std=0保持原策略动作；参数为CLI显式配置，每次重启都需携带，不能依赖上次状态文件自动启用。
- 这不是热更新，原先已启动的进程需正常退出后重启才能加载实现。

启动打印 `EXPLORATION`；`async_state.json` 和Actor遥测保存配置。
每条受扰动动作的原始NPZ metadata记录 `exploration`：原策略动作、限幅噪声、实际施加差值及配置。
`normalized_action`/`wire_action`记录实际加噪后的命令。
导出的ready片段和cached直接源读取均保留 `command_audit.exploration`，训练动作标签继续使用实际命令。
人工及握手记录的exploration为null，不会继承前一条策略动作的噪声。

## 本会话续跑命令

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_cached_online_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 2 --publish-every 50 \
  --reload-every-episodes 10 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 \
  --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

此命令恢复已有会话，不重新初始化BC或缓存；将std设为0可关闭探索。
监控仍使用本会话的8768入口，见[在线启动记录](../../../../replay/records/training/chronicles/2026-10-11-cached-online-start.md)。

## Learner到Actor的权重交接

Learner每50次Critic更新原子发布本会话的 `actor.pt` 与 `learner.pt`，正常退出也保存最终权重。
Actor在本次加载后每新增10个有效回合检查一次；在回合结束、停止动作后进行加载，回合中策略保持固定。
加载检查验证契约、recipe与探针输出有效性，不代表验证了任务性能。

**17:53:55（Asia/Shanghai）只读快照**：Actor和Learner均已正常CLOSED，无error。
Actor最后版本0、完成1个有效回合；Learner更新及最终发布版本均4777，已达到当时训练预算。
因此当时的4777尚未被该Actor执行，但下一次启动同一目录会直接加载最新4777，无需等剩余9回合。
启动日志应出现 `POLICY_LOADED: version=4777`；若此后另有训练发布，则以实际最新版本为准。
重启时会以已完成回合数重置本次换权重检查基点，之后每新增10个有效回合检查。
若将 `--reload-every-episodes` 改为1，则每个有效回合结束检查；本次没有替用户改成1。

## 验证范围

- 首批相关回归71项通过；新增状态持久化与双回放路径测试后，探索专项13项通过（包含此前11项）。
- 覆盖噪声/动作双重限幅、无噪声逐值一致、两种仲裁的人工和握手保护、无候选不抽样、
  非法CLI参数在连接机器人前失败、实际周期记录动作与噪声一致、两种replay保留实际标签及审计。
- 在线启动脚本的help已能识别新参数。相关验证不发布机器人动作；真机探索效果仍待现场采集评估。
- 另用真实4777检查点和真实录制观测，在CPU走实际策略仲裁路径100次，确认随机扰动、
  每轴噪声上限与最终动作范围，检查点SHA-256前后一致。
  报告在 `local/diagnostics/online_exploration_20261011_01/report.json`，没有ROS或机器人输出。

代码入口：`hil/exploration.py`、`hil/async_training.py`、`hil/periodic_control.py`，
以及两条回放导入路径 `hil/periodic_replay.py`、`training/replay_sources.py`。
