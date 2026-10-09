# BC12045 预加载与异步 RL 首次试跑

日期：2026-10-09。使用当前 latest 观测驱动控制与默认的推理完成后仲裁。

现场更新：本会话已运行两个回合，均报告 `sdk_rejected`，原始记录保留、未入训练池。
接收端已修复一个通道切换缺陷并增加SDK失败诊断，**需要先停止Actor，在现场按原命令重启接收端，
再重启Actor**；仅重启训练脚本不够。拒绝底层原因仍未确认，不把本次修复当作已完成真机验收。
详见[故障证据与修复范围](../docs/agent/training/chronicles/2026-10-09-sdk-rejection-and-handoff-audit.md)。

## 本次准备的模型与目录

| 项目 | 内容 |
| --- | --- |
| BC 来源 | `local/bc_episodes/demo_new_20261007_213643_eval_01/actor.pt`，BC version 12045 |
| 新 RL 会话 | `local/rl_training/bc12045_obs_after_inference_20261009_01/` |
| 初始策略 | 完整继承 BC12045 的 Actor、编码器与归一化参数，逐张量核对一致 |
| 初始示范 | 对应 BC 的 11 段、1387 条人工数据；在线池与在线干预池从零开始 |
| 回合 | 每回合 20 秒，Start 手动开始 |
| 训练 | 编码器冻结，前 1000 次更新仅 Critic；随后满足在线样本门槛才进行 SAC+BC 更新 |

此目录用于新一轮试跑。旧 `bc_demo_new_20261007_213643_rl_live_01` 已到 RL version 6502，
不能将续跑旧目录称为重新从原始 BC 开始。本次不覆盖旧会话、BC 或种子。

本次已完成离线准备与 GPU 检查：初始 Actor、归一化和 recipe 与 BC 一致，
同一条真实录制观测的 CUDA 输出逐元素一致；RTX 5060 Laptop GPU 上预热后 5 次前向约 4.59–6.75 ms。
这只是离线网络前向，不含传感器/ROS/机械臂时延。没有启动机器人或运行 Learner 更新。
证据在会话内 `bc_initialization.json` 与 `offline_validation.json`。

## 启动前三个要点

1. 保持机器人接收端、外部 RGB、腕部 RGB ROI、双指触觉三场及 EEF 反馈运行。
   从未启动时，按[常用现场启动指令](common_live_commands.md)配置机器人与传感器。
2. 同一时刻只运行一个动作发送入口。先正常结束其他手柄、采集、BC 或 RL 控制脚本并等待保存。
3. 本次使用 domain 13 和 SUBNET 发现；接收端与网络传感器需要相同的发现配置。
   本模型不需要六维 wrench 输入。

## 首次试跑：直接复制

新会话已离线准备后，只需要下面这一条启动流程：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_obs_after_inference_20261009_01 \
  --actor-device cuda --learner-device cuda \
  --episodes 3 --reload-every-episodes 10 \
  --batch-size 2 --publish-every 50 \
  --arbitration-mode after-inference \
  --execute --enable-policy
```

这是异步 RL 入口，后台 Learner 同时运行。首次先做最多 3 个回合，而换权重间隔为 10 个有效回合，
因此这次首次启动的 3 个回合保持最初加载的 BC Actor 行为，方便观察模仿学习结果；
Learner 可以在后台更新，但不在这 3 个回合中把更新后的 Actor 切入控制。
这不是永久冻结 BC 的评估模式，下一次重启会加载该 RL 会话当时最新的 Actor。

启动应看到 `ARBITRATION_MODE: after-inference`、`POLICY_LOADED` 和等待 Start 的提示。
`POLICY_LOADED` 显示的是 RL 更新计数，可能为 0 或 Critic 预热中的版本号，不一定显示 12045；
是否源自 BC 以初始化记录与权重核验为准。

| 操作 | 当前行为 |
| --- | --- |
| Start（315） | 开始一个回合 |
| 回合内 RB 松开 | 每次推理完成后采用 policy 动作 |
| 回合内按住 RB＋摇杆 | 每次推理完成后读取最新手柄输入，用人工动作替代 |
| 回合内按住 RB、摇杆回中 | 推理完成后选择人工零动作 |
| 308 | 标记成功并结束回合 |
| 307 | 提前结束回合，不标成功 |
| 回合外 RB＋摇杆 | 人工复位，不进入训练样本 |
| 回合外 Back（314） | 回 home |
| A / B（304 / 305） | 夹爪闭合 / 张开 |
| Ctrl+C | 停止输出，等待保存并退出本次 Actor/Learner |

新默认模式下，按下或松开 RB 不会立即切换，控制来源在推理完成点选择；
停止、结束和断连继续由主循环及时处理。按住 RB 时推理仍继续。
原立即人工接管模式仍可用，把上面参数改成 `--arbitration-mode immediate`。
推理超过 100 ms、EEF 因果和帧龄问题只记录时序诊断；接收端原有的断流停止参数未修改。

## 只读监控（另一个终端）

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_obs_after_inference_20261009_01 \
  --port 8768
```

浏览器打开 `http://127.0.0.1:8768`。重点看仲裁模式、实际控制来源、Actor 已加载版本、
Learner 更新与 ready/imported 数据链。源时序诊断与真正的数据排除分别显示。

## 后续继续训练

继续此目录时不需要 `--resume`。重复主命令会加载最新已发布的 RL 权重，不会重新加载原始 BC。
需要连续训练时去掉 `--episodes 3`，或显式设置更大的回合数；回合仍由 Start 开始。
若希望再次从原始 BC 对照，另建新目录，不能覆盖或重置这次数据。

## 初始化的复现命令（仅创建另一个新会话时使用）

下面示例会创建 `_02`，已经准备好的 `_01` 不需要再次初始化。准备过程不连接机器人：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run local/rl_training/bc12045_obs_after_inference_20261009_02 \
  --capacity 4000 --intervention-capacity 2000 \
  --critic-warmup-updates 1000 --bc-weight 10 --actor-learning-rate 0.00001
```

创建后将主命令的 `--run` 改成新目录。初始化拒绝覆盖已有目录。
仲裁实现与验证见[开发记录](../docs/agent/training/chronicles/2026-10-09-arbitration-modes.md)，
完整训练机制见[异步 RL 教程](async_rl.md)。
