# 2026-10-07：人工周期采集现场联调与多回合操作

## 当前状态与适用入口

纯人工真机 RL 示范使用 `scripts/collect_rl_episodes.sh --control-mode periodic --execute`。
脚本不加载策略、不启动 Learner；`--episodes N` 最多采 N 个已结束回合，默认入口的
`receipt` 是旧同步模式。周期模式以 100 ms 为目标持续发布命令，不逐条等待回执；
回执、下一观测和 EEF 因果检查在后台审计，合格的连续片段导出到训练用 `episodes/`。
这表示接收端接受了命令，不表示已测得同等位移。完整原始记录保留在 `periodic_episodes/`。

本轮已经由操作者现场确认：315 能进入 `ACTIVE`，按住 RB（311）并推动摇杆能产生非零动作；
Back（314）可在回合外回 home；A/B（304/305）可提交夹爪开合。未由本记录独立测量
机械臂位移或任务成功率。软件测试验证保存期间 Start 排队和周期采集状态机；
**这项排队改动尚需重启旧采集进程后现场复验**。

## 操作命令

在项目根目录运行。启动前确认接收端、传感器和手柄就绪，只保留一个采集控制发布者：

```bash
bash scripts/collect_rl_episodes.sh \
  --output "local/rl_episodes/demo_new_$(date +%Y%m%d_%H%M%S)" \
  --episode-seconds 20 --episodes 10 \
  --control-mode periodic --execute
```

每次使用新目录；若要在同一会话目录按回合边界续采，使用原配置与
`--output <原目录> --episode-seconds 20 --control-mode periodic --resume --execute`。
新代码只会被新进程加载：仍在运行的旧采集进程需要先在其终端按 Ctrl+C，等退出后再启动。
脚本设置 ROS domain 13（若未另设）、`ROS_LOCALHOST_ONLY=0` 和
`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`，以接收外部机器的 RGB。

| 阶段 / 输入 | 行为 |
| --- | --- |
| `WAIT_START`，按 315 | 启动一个回合，打印 `ACTIVE` 及青色中文开始提示；计时从接受 Start 开始 |
| `ACTIVE`，持续按 RB 311 并推动摇杆 | 发送人工六维动作；松开 RB 或摇杆回中发送零动作；再次按 315 不重启当前回合 |
| `ACTIVE`，按 308 | 截止时间前标记成功并结束，打印 `EPISODE_RESULT: SUCCESS` 和绿色中文结果 |
| `ACTIVE`，按 307 | 提前结束，保持非成功标签，打印 `MANUAL_STOP` 和黄色中文结果 |
| 达到回合时限 | 自动结束，保持非成功标签，打印 `TIMEOUT` 和黄色中文结果；之后按 308 不能追认成功 |
| 保存期间按 315 | 新版本记下这次 Start，保存完成后再开始下一回合；回合未结束时按的 Start 不排队 |
| 回合外按 Back 314 | 自动回 home，复位动作不写入训练片段；回位期间不能启动回合 |
| 任意阶段按 A/B | 提交夹爪闭合/张开，先松开再按才能再次触发；不作为六维 RL 动作标签 |

成功、超时和 307 提前结束会按原标签保存有效片段；异常、缺失或不合格间隔不会被拼接成
完整轨迹。按键采用按下边沿；第一次使用或重连后先松开再按。后台保存完成后，若没有
排队的 Start，程序继续停在 `WAIT_START`，等待下一次 315。完成 N 个回合后进程退出；
中途按 Ctrl+C 会停止并收尾，未完成回合只留审计。

## 终端读数与数据含义

- `HUMAN_PERIODIC: {"phase": "ACTIVE"}` 和 `ACTIVE:` 是进入控制回合的英文标记；
  青色中文横幅同时提示 RB 操作。彩色横幅仅在交互终端显示颜色，`NO_COLOR` 可关闭颜色。
- `PERIODIC: ticks=... rb=True nonzero_action=True` 是当前一次打印时的 RB / 非零动作状态；
  每 10 个 tick 打印一次，不能把单行 `nonzero_action=False` 当成整回合全零。
- `EPISODE_RESULT` 给出成功、手动结束、超时或异常的英文判定；紧随其后的彩色中文横幅
  给出相同结论。`PERIODIC_SAVED` 和 `HUMAN_PERIODIC: EPISODE_RECORDED` 是审计明细。
- 保存后打印“有效动作 X 条、非零动作 Y 次”和“已完成 i/N 回合、本次运行累计有效动作”。
  `ticks` 是发出的周期命令数，`transitions` 是通过回执与因果观测校验后导出的条数；
  `nonzero_action_ticks` 是全部 tick 中非零命令次数，未必每次都属于导出片段。
- `training_ready=true` 只表示结构和时序校验通过。全零动作回合也可能出现这个标志；
  正式训练前仍需审查实际运动、成功标签、非零动作比例及有效片段。

2026-10-07 现场第一回合样例：`d04c573dd26e44f5b3f607fb722b80e0`，20 秒到时，
`ticks=200`、`transitions=189`、`nonzero_action_ticks=105`，排除 10 个缺观测间隔和
1 个非因果间隔；`success=false`。操作者随后在保存期间按了 315，旧进程仍清掉这次按键，
因此第二回合没有启动。这是排队改动的直接依据，并不说明只能采一回合。
此前另一现场回合 `7780472d63984cbaa58e1a23627ef757` 有 144 条有效片段，但
`nonzero_action_ticks=0`，说明仅看 `training_ready` 不足以判断示范质量。

## 本轮实现与验证边界

- 修正局域网 ROS 发现，外部 RGB 可进入观测；刚按 Start 时出现短暂
  `missing_or_stale:rgb` 不等于 RGB topic 不存在，需看后续历史是否完整。
- 旧 `receipt` 模式在非零命令的约 100 ms 回执等待后容易越过 100 ms 新鲜度界限，
  因此人工连续采集推荐周期模式。人工作业周期发送相对观测参考格延后约 30 ms，
  避免格点边缘抖动造成大量非因果片段。
- 周期模式保留原英文状态与审计 JSON，同时增加青色开始、绿色成功、黄色非成功、
  红色异常的中文横幅；保存摘要给出本回合及本次运行累计条数。
- 修复保存阶段 Start 事件被 `idle_tick()` / `wait_start()` 清除：只保留回合停止后
  新按下的 Start，并在真正进入下一回合时开始新的 20 秒计时。
- `tests/test_periodic_control.py` 与 `tests/test_rl_episode_collection.py` 共 27 项通过，
  `git diff --check` 通过。这些是本机软件验证；排队 Start、累计统计和颜色变更尚无
  新进程现场日志，不能据此宣称完整实机验收。

操作详情及历史模式差异见[采集教程](../../../../tutorials/rl_episode_collection.md)。
