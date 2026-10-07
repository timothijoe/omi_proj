# 2026-10-07：新采人工周期数据的两阶段 BC 训练

## 数据与方法

源目录：`local/rl_episodes/demo_new_20261007_213643`。10 个现场回合中 9 个按成功结束、
1 个超时；周期后台审计导出 11 个连续 ready 片段，共 1387 条人工动作。部分成功回合
被数据间隔拆段，只有含有效终点的片段带成功标记；BC 监督使用命令动作，不用奖励选择样本。
原始数据未改动，没有启动机器人发布者或 Learner。

沿用今天全量拟合方案：从旧 BC version 295 开始，保持观测、动作表示、网络结构和原模型
归一化不变，冻结预训练视觉骨干；其余原有可训练编码器与 Actor 均值头训练。
batch16、seed7，Adam 先 4000 步、lr=1e-4，再从第一阶段最佳点重新建立 Adam，
细调 8000 步、lr=1e-5。最佳权重按**全部 1387 条训练样本的动作 MSE**选择。
11 个片段全部用于拟合，**没有独立验证集**，也没有真机成功率结论。

## 周期标签校验的作用范围

周期片段使用 `periodic_accepted_command`，回执语义是接收端接受命令，不是位移完成。
原旧同步标签校验器要求单条完成回执，不能读取这个新格式。本轮新增
`hil/periodic_bc_label.py`，只由 BC 读取器和 BC 专用索引工具调用：检查命令 ID、
人类动作来源、归一化/物理/线缆动作换算、100 ms 观测区间、接收回执与后续 EEF 因果顺序。
**通用 `demo.validate_command_label`、`TransitionReplay`、RL 导入和控制框架未放宽或增加
周期格式规则。**通用校验器仍拒绝周期格式；这一点有回归测试覆盖。

训练实际使用的索引在 `local/rl_training/bc_seed_demo_new_20261007_213643_v3/dataset.json`。
该索引是在训练准备阶段生成的。收窄代码作用范围后，又用 BC 专用工具生成
`local/rl_training/bc_index_demo_new_20261007_213643/dataset.json`；两份索引的
11 个片段、ready manifest 哈希和 1387 个样本哈希逐项一致。两者的临时训练/验证
分组不同，因此替换索引重新跑不保证相同随机抽样顺序或逐位相同权重；本次全量拟合
没有独立验证分组。后续新周期数据可用 BC 专用索引命令：

```bash
PYTHONPATH=src local/cuda-env/bin/python -m omi_hil_rl.hil.prepare_periodic_bc \
  --source local/rl_episodes/新采集目录 \
  --output local/rl_training/新的BC索引目录
```

本次拟合命令（`--output` 和 `--prepare-output` 均必须换为不存在的新目录）：

```bash
PYTHONPATH=src local/cuda-env/bin/python -m omi_hil_rl.hil.fit_all_bc \
  --checkpoint local/bc_episodes/bc_ready_20261007_01/actor.pt \
  --dataset local/rl_training/bc_seed_demo_new_20261007_213643_v3/dataset.json \
  --output local/rl_training/新的BC训练目录 \
  --prepare-output local/bc_episodes/新的BC评估目录 \
  --coarse-updates 4000 --fine-updates 8000 --device cuda
```

## 产物与结果

| 项目 | 本次结果 |
| --- | ---: |
| 源 BC 版本 | 295 |
| 训练步数 | 12000 |
| 最佳新增步数 / 模型版本 | 11750 / 12045 |
| 全量归一化动作 MSE：训练前 / 最佳 | 0.650336 / 0.004515 |
| 最差单片段训练 MSE | 0.006771 |
| 冻结视觉骨干 | 逐张量未变化 |
| 模型保存后重载预测最大差 | 0 |

训练目录：`local/rl_training/bc_demo_new_20261007_213643_coarse_fine_01/`，包含
`actor.pt`、`report.json`、`history.json`、`dataset.json` 和训练前后预测文件。
独立 BC 评估快照：`local/bc_episodes/demo_new_20261007_213643_eval_01/`，
`bc_session.json` 标明 version12045、`learner_enabled=false`。准备快照没有执行真机动作。

现场操作者如需只测试一个真机推理回合，可在外部传感器和接收端就绪、没有其他动作发布者时运行：

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

脚本会加载上述固定 version12045；315 开始，按住 RB 人工接管，308 标记成功，
307 提前结束。脚本已对齐采集入口的局域网 ROS 发现，以接收外部 RGB。
这个命令是实时网络推理，不是回放训练标签；评估时不更新权重。

这是同数据拟合指标；模型仍需独立现场评估，不能由训练 MSE 推断机器人插接成功率，
也不能直接当作 SAC Learner checkpoint 使用。新数据尚未自动导入旧双池 RL 会话。
相关 BC/旧标签测试 14 通过、1 跳过；本批 1387 条逐条校验通过，`git diff --check` 通过。
