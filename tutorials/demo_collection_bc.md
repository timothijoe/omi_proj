# 集成手柄 Demo 采集、指令标签与 BC

本篇介绍集成手柄采集入口。当前用户选择独立 `gamepad_test.py` 遥操作，默认 `record_demo_bag.sh` 已改为纯录包，见[独立录制教程](demo_bag_dataset.md)。下方直接调用 `hil.demo collect` 的集成模式保持独立。

当前独立录包与可视化见[操作教程](demo_bag_dataset.md)。只有本文集成collector生成的bag包含精确样本快照，可使用快照转换器脱离采集目录恢复数据集。

入口为 `omi_hil_rl.hil.demo` 和 `omi_hil_rl.training.demo_bc`。
采集不需要策略权重或 learner；先保存观测和人工动作，后续独立标注 reward。
已通过合成闭环、真实多模态网络 CPU/CUDA 梯度及隔离 ROS 录包测试，尚未采集本流程的真机示范或测量插入成功率。

## 采集什么

同时保存两种数据：

- `raw/`：ROS 原始消息，默认包含模型观测来源，以及关节反馈、腕部原图/ROI、双指 wrench、两个控制输出 topic、指令追踪、回执和按钮/回合事件。
- `episodes/<id>/000000.npz`：发送前观测、下一观测、最终采用的人工动作、时间戳与指令审计。观测包括双 RGB、触觉、EEF 状态及历史/相机 mask；模型不使用关节和夹爪。

默认录制 `/omi/action/decision`、`/omi/action/manual_decision`、`/omi/action/command_trace`、`/omi/action/receipt` 和 `/omi/demo/event`。
默认列表不是 ROS 上所有 topic；`--all-topics` 录制所有发现的 topic，或重复 `--raw-topic /your/topic` 补充。
未发布的传感器不能凭空保存；退出后 `raw_recording.json` 列出消息数和没有消息的请求 topic，`rosbag.log` 保留录包日志。
录包程序退出会中止有效采集，但这不等于证明 DDS 没有丢帧。

标签是 **观测之后实际发送并得到匹配回执的六维人工指令**。训练数组 `executed_action` 为 [-1,1] 的动作，
`action_m_rad` 保留转换前的 m/rad 六维增量；`command_trace` 同时保存发送到 SDK 接口的数值、转换约定、时间及 command ID。
原始 `Float64MultiArray` topic 使用 mm/SDK ABC，不能直接当作 m/rad 标签。
保存前及训练读取时均校验 ID、发送时间、前后观测顺序、单位转换和回执数值。
SDK 已发送回执不代表机器人已经物理到位，动作语义仍是 accepted_command。

停止、回合外手动复位也写入原始 bag，并标记 `label_candidate=false`，不混入训练样本。
回合内 RB 按住时的有效零动作可以作为标签。控制端拒绝、修改命令或反馈缺失会使该回合无效。

## 先跑无硬件流程

在仓库根目录运行；每次使用新目录，避免覆盖已有示范：

```bash
source scripts/env.sh
python -m omi_hil_rl.hil.demo collect --directory local/demo-first --episodes 6 --fake-steps 8
python -m omi_hil_rl.hil.demo inspect --directory local/demo-first
python -m omi_hil_rl.training.demo_bc plan --demos local/demo-first \
  --output local/demo-first-plan.json --validation-episodes 2
python -m omi_hil_rl.training.demo_bc train --plan local/demo-first-plan.json \
  --output local/demo-first-bc --steps 100 --batch-size 8 --evaluate-every 20
python -m omi_hil_rl.training.demo_bc evaluate --plan local/demo-first-plan.json \
  --checkpoint local/demo-first-bc/actor.pt
```

未指定 config 时使用 fake transport 和明确标记的合成动作/观测，仅验证流程，不是人类示范或插入效果。

## 真机手柄采集

先按现场教程启动传感器与控制接收端。停止已有 gamepad/policy 发布进程：此采集入口自己读取手柄并发送指令，
不与另一个手柄控制节点同时运行。它使用受保护的 `/omi/action/decision`，不走 manual topic 的保护绕过路径。
旧 gamepad 节点不会自动产生新增 command_trace，旧 bag 也不会自动转成此格式。

生成配置（SDK 安装坐标约定和 EEF reference 应按现场已确认配置设置）：

```bash
source scripts/env_ros.sh
python - <<'PY'
from dataclasses import asdict
from pathlib import Path
import json
from omi_hil_rl.hil.config import HILConfig
p = Path('local/demo-config.json')
p.parent.mkdir(parents=True, exist_ok=True)
with p.open('x') as f:
    json.dump(asdict(HILConfig(transport='ros')), f, indent=2)
PY
```

默认 10Hz，开始后 15 秒，计时包括约 1 秒观测历史预热；每轴平移上限约 0.577mm、旋转向量分量约 0.577°。
先只读预览：

```bash
python -m omi_hil_rl.hil.demo collect --config local/demo-config.json \
  --directory local/demo-preview --episodes 3
```

没有 `--execute` 时不创建动作发布者，只检查观测并录包，不生成 BC 示例。
现场准备完成后，使用新目录运行采集：

```bash
python -m omi_hil_rl.hil.demo collect --config local/demo-config.json \
  --directory local/demo-real-01 --episodes 10 --execute
```

| 阶段 | 操作 |
|---|---|
| 等待开始 | 按住 RB，用摇杆手动调整起始位置；这些复位指令仅录包 |
| 开始 | Menu/开始键触发计时；开始后必须按住 RB 才能采集人工指令 |
| 示范 | 按住 RB 进行六维控制；松开 RB 会使纯人工示范无效 |
| 结束 | Y 标记成功，或等待超时；运行中 B 中止并丢弃 |
| 审核 | A 保留，B 丢弃；有效超时段也可保留 |
| 下一回合 | 审核后回到等待开始，可再次用 RB 手动复位 |

Y 是当时的人工结果记录；A/B 是数据是否保留，两者分开。
开始/成功/保留/丢弃按钮码可在 config 修改。采集中的当前/下一窗口驻留内存，历史示范逐条压缩落盘。
Ctrl-C 中断时未完成审核的 staging 段不会进入 BC 数据集，原始 bag 保留已有内容。

## 真机数据训练与检查

至少需要两段保留的有效 episode，训练/验证按整段分开，不把同一段 transition 随机分到两边。
可重复 `--demos` 合并多场同契约采集；`--success-only` 只选择人工标为成功的段，默认包含所有保留的有效段。

```bash
python -m omi_hil_rl.training.demo_bc plan --demos local/demo-real-01 \
  --output local/demo-real-plan.json --validation-episodes 2
local/cuda-env/bin/python -m omi_hil_rl.training.demo_bc train \
  --plan local/demo-real-plan.json --output local/demo-real-bc \
  --pretrained local/pretrained/serl_resnet10/backbone.pt \
  --device cuda --steps 500 --batch-size 32
local/cuda-env/bin/python -m omi_hil_rl.training.demo_bc evaluate \
  --plan local/demo-real-plan.json --checkpoint local/demo-real-bc/actor.pt --device cuda
```

真机 BC 使用 current9stack 多模态 Actor，冻结官方 ResNet-10，训练历史首层、融合层与动作均值头。
归一化统计只从训练集计算；数据集在内存保留索引，按需读取磁盘 NPZ。文件哈希绑定划分，修改数据后需生成新 plan。
BC 不需要 reward 或 Critic；Critic 在后续 RL 阶段训练。

`report.json` 包含验证集归一化 MSE、平移 RMSE(mm)、旋转分量 RMSE(°)，以及零动作/训练均值基线。
`actor.pt` 是验证 MSE 最优权重，`last.pt` 保留最后训练状态。离线误差只能说明动作模仿程度，不能替代真机成功率。
可用现有 Actor 做只读确定性预测，无需 learner：

```bash
source scripts/env_ros.sh
local/cuda-env/bin/python -m omi_hil_rl.hil.actor --run local/demo-real-bc \
  --config local/demo-config.json --deterministic
```

此命令没有 `--execute`，不发送动作。BC 输出目录不要直接交给 learner：目前未实现 BC 权重自动初始化 SAC，learner 可能发布新的随机 SAC 策略覆盖该文件。

## 后续 reward 标注

采集文件没有 reward 数组，按钮结果仅是原始元数据。看过观测后可新增独立标签版本：

```bash
python -m omi_hil_rl.hil.demo annotate --episode local/demo-real-01/episodes/EPISODE_ID \
  --outcome success --success-step 25 --version v1 --note '人工回看确认插入'
```

step 从 0 开始；成功标注取到该步，末步 reward=1、terminated=true，其余为 0。
`timeout` 为全 0，最后 truncated=true；`failure` 为全 0，最后 terminated=true。
结果写入 `reward_v1.json`，不修改原始观测/动作，也不覆盖同版本文件；BC 不读取这些 reward。
新入口只发布 `demo.json`，不会发布 RL 的 `ready.json`，因此未标注示范不会自动流入 learner。
后续 RL 导入还需明确选择 reward 版本并构造完整 transition，本次未增加自动导入。
