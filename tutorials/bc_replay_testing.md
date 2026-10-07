# BC模型测试与成功动作label回放

本页区分“网络预测”与“播放标签”，避免用错入口。
开发背景、训练结果和未完成项见[开发记录](../docs/agent/training/chronicles/2026-10-07-periodic-replay-bc-fitting.md)，
训练复现见[详细教程](async_rl.md)。

## 模型选择与冻结范围：先明确这三点

- 原BC295：6回合训练、2回合验证；训练到第13轮早停，推理用的是验证动作MSE最低的第5轮模型，
  不是最后一轮，也不是按真机成功率选出的模型。
- 新BC11795：全部8回合训练，长时间拟合后降低学习率细调；按训练MSE选模型，没有独立验证集。
  两次BC都只冻结预训练视觉骨干，触觉编码器、视觉历史输入/投影、融合层和动作均值头都参与学习。
- 最新保护式RL与BC不是同一冻结设置：RL目前冻结整个Encoder，1000步以后也不自动解冻。
  历史9帧输入层在BC中可以更新，尽管它由预训练卷积权重初始化；复用的ResNet骨干仍冻结。

权重实测、为什么不能把拟合改善等同泛化改善，以及新RL开发证据，见
[完整交接记录](../docs/agent/training/chronicles/2026-10-07-bc-protected-rl-and-encoder.md)。

## 1. 测试最新8回合模型

提前启动传感器和接收端，退出其他动作发布程序；人工复位机器人并检查物体、夹持状态。
先在可安全运动的位置进行一个回合测试，保留急停和RB接管。

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/all8_coarse_fine_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

应显示`OVERFIT_EVAL`及`POLICY_LOADED: version=11795`。
这是根据实时观测推理，不是按顺序播放训练label。没有Learner，测试时不训练或刷新权重。

按键：315开始，RB+摇杆人工优先，307提前结束，308标记成功结束，Ctrl+C停止退出。
本命令完成一个回合后退出；若需继续测试，重新运行同一命令，`--resume`不覆盖旧记录。

## 2. 切换模型做对照

仅替换上面命令的`--output`，其他参数保持一致：

| 模型 | 已准备目录 | 版本 |
|---|---|---:|
| 原6训练/2验证BC | local/bc_episodes/bc_ready_20261007_01 | 295 |
| 单回合拟合模型 | local/bc_episodes/overfit_71960_eval_01 | 3295 |
| 全8回合拟合模型 | local/bc_episodes/all8_coarse_fine_eval_01 | 11795 |

这些目录有各自的权重快照。`--resume`使用目录中的模型，不靠`--checkpoint`偷偷切换。
不要同时运行多个模型进程，也不要把这些BC目录当作`run_async_rl.sh`的SAC恢复目录。

全8回合模型训练MSE为0.00088644，但8个回合都用于训练，没有独立验证集。
单回合模型能拟合原记录，也不证明更换起点后可靠。均未建立真机成功率结论。

## 3. 播放成功记录的BC label，而不是网络输出

这条171步成功示范ID为`71960bbce1d24bd9ad9060cb95d0663f`。

```bash
# 只打印和检查，不连接机器人
bash scripts/replay_success_episode.sh \
  --episode local/rl_episodes/test_20261007_161750/episodes/71960bbce1d24bd9ad9060cb95d0663f

# 明确要真机回放时再运行
bash scripts/replay_success_episode.sh \
  --episode local/rl_episodes/test_20261007_161750/episodes/71960bbce1d24bd9ad9060cb95d0663f \
  --output "local/action_replay/test_$(date +%Y%m%d_%H%M%S)" \
  --execute
```

日志必须显示`RECORDED_ACTION_REPLAY`、正确源episode、`neural_network=false`，不会加载BC模型。
`normalized`是记录的六维BC label；`wire`是经过与policy相同的换算和发布链路得到的SDK指令。
不是模拟手柄输入，也不是用末端位移代替标签。

315开始；起点偏差超过10mm或5度拒绝播放，不自动回到起点。此阈值不是接触安全保证。
保留原发送间隔，不保证物理轨迹复现。RB会取消序列、允许人工接管，松开不会继续播放；
307/308停止，Ctrl+C退出。序列完成后停住，仍可人工复位；再次播放需重启命令。

## 4. 记录、停止和安全边界

- BC periodic模式目标100ms发一次，不逐条等完成回执。缺失/过期/已使用候选变零，
  持续1秒没有已知命令回执、接收端错误或手柄断连仍停止；并非关闭全部超时保护。
- BC每回合保存在运行目录的`periodic_episodes/<id>/`，Ctrl+C先停止再排空后台记录。
  数据当前为审计格式，`training_ready=false`，**不会自动进入BC或RL训练池**。
- label回放保存`source.json`、`commands.jsonl`；正常完成保存`result.json`。
  中断/异常退出可能没有result，但已写的命令日志保留；这些同样不是新的训练示范。
- `--control-mode receipt`才是旧同步transition采集；这与periodic的记录格式不同。
- `run_async_rl.sh`没有因本次BC改动自动切换为periodic，也没有自动加载上述BC模型。
- 当前输入仍是既有无wrench配置，动作空间和缩放未改；不要为了方向异常直接反转dx。
