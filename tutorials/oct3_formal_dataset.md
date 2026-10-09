# oct3正式录包：检查、转换与训练

2026-10-09 存储更新：已导出的 `local/datasets` 已迁到 `omi_proj_data/local/datasets`，
原路径保留软链接；读取数据须挂载移动盘。`local/eef_history` 的模型与报告保留本机，
见[存储教程](local_data_storage.md)。

**当前划分更新**：按用户说明，bag_002包含反复尝试，已移入训练，验证改为bag_004/008。
新训练1283样本、验证242样本；单帧与历史模型均重训，产物在`local/eef_history/oct03_split2/`。
新计划为该目录`plan.json`，历史训练命令将下文`--plan`替换为此文件，并选择新的输出目录。
最佳历史模型200步验证0.846mm/0.003381rad，详细结果见
[新划分记录](../docs/agent/training/chronicles/2026-10-03-validation-resplit.md)。
下文旧划分命令保留用于复现早期实验，不代表当前验证集选择。

源目录：`/media/zhoutong/zt-think-d1/recorded_data_formal/oct3_record_data`。
以下命令从 `omi_proj/` 执行，输出目录必须不存在。原ZIP不修改。

## 本轮结果

10包、172.89秒、329268条消息，导出1525个样本。
完整报告在 `local/datasets/oct3_formal/review.md`，机器可读审计为同目录 `audit.json`。
正式数据仅使用 `local/datasets/oct3_formal/datasets/bag_001` 至 `bag_010`。
训练方案为 `training_plan.json`，命令为 `proposed_train_command.txt`。
用户确认后已完成2000步首轮训练，结果在 `local/eef_bc/oct3_formal_v3_run1/`。
验证平移RMSE1.037mm、旋转0.004172rad，未优于零动作/均值动作基线；
见[完整训练记录](../docs/agent/training/chronicles/2026-10-03-formal-training-run1.md)。

## 检查新录包

在已安装本项目ROS依赖和marvin_msgs的本机环境：

```bash
source scripts/robot_viewer_env.sh "$PWD"
source /opt/ros/jazzy/setup.bash
source "$OMI_MARVIN_MSGS_SETUP"
export PYTHONPATH="$PWD/src:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/python scripts/audit_eef_recordings.py \
  /media/zhoutong/zt-think-d1/recorded_data_formal/oct3_record_data \
  local/datasets/oct3_formal_reaudit
```

审计读取所有消息，核对数量、反序列化、header顺序、接收时间差、图像格式、有限数值、
EEF四元数及图像重复载荷，并输出相机缩略图。这些检查不能自动标注任务成功。

## 转换单包

```bash
bash scripts/eef_bc.sh export \
  /media/zhoutong/zt-think-d1/recorded_data_formal/oct3_record_data/bag_001.zip \
  local/datasets/oct3_formal_new/bag_001 \
  --accept-future-state-proxy --wrist-camera optional --input-profile grid-receive
```

新版本 `bag-eef-bc-v3-grid-receive`：

- 外部RGB与腕部RGB各3×128×128；腕部已是ROI，不重复裁剪。
- 双指触觉10×16×24；已是小矩阵，不重复池化。
- state14＝7关节＋EEF位置/四元数；wrench无消息，因此排除，不填零。
- action6＝未来EEF变化，米与基座系旋转向量弧度；仍是代理标签，不是实发控制命令。
- 按录包接收时间对齐，original_source_ns/original_label_ns保留原header。
- 原设备时钟未校准；正常触觉header比接收快约28–32ms，不做隐式偏移校正。
- 入口丢弃接收−header>250ms（EEF>50ms）或header超前>100ms的消息；
  参考点观测年龄阈值250ms/EEF50ms，标签间断阈值50ms。
- 接收时钟版本目前仅支持离线数据和训练，不能使用现有在线shadow入口。

每包产物：`samples.npz`、`manifest.json`、`references.json`、选中原始帧的`observations/`。
缺失/过期参考点及入口异常源消息分别计数，不能把两者直接相加当作剔除样本数。

## 本轮训练与复查

最新单帧/历史模型对照集中维护于[oct_03训练日志](../docs/agent/training/evolution/oct_03-training-log.md)。

本轮将bag_002与bag_008作为整包验证集（390样本），其余8包训练（1135样本）。
2000步、batch32、Adam lr0.001、seed7、CPU。保留零动作/均值动作基线。
第一轮没有独立测试集；单帧训练器记录训练loss和最终验证指标，不提供逐步验证曲线。
用户回复“好的，请你继续呀”后执行了已准备的训练命令；成功/失败仍未独立逐包标注。
模型为 `policy.pt`，完整报告为 `report.json`，曲线为 `training_curve.png`，
验证预测图为 `bag_002_validation.png` / `bag_008_validation.png`。
曲线重画命令（需另选不存在的输出文件）：

```bash
/usr/bin/python3 scripts/plot_eef_training.py \
  local/eef_bc/oct3_formal_v3_run1/report.json \
  --output local/eef_bc/oct3_formal_v3_run1/training_curve_copy.png \
  --title 'oct3 formal | 8 training bags | 2000 steps'
```

## 最近1秒历史训练

原来的单帧结果保留。历史模型独立入口，使用同一训练计划和原数据：

```bash
env -u PYTHONPATH .venv/bin/python -m omi_hil_rl.training.eef_bc_history \
  --plan local/datasets/oct3_formal/training_plan.json \
  --output local/eef_history/oct03_run1 --steps 2000 --seed 7
```

输出目录必须不存在，重做实验请换run名。
10个固定100ms时刻从t−0.9s到t；缺失历史mask掉，不跨录包，不用未来观测。
CNN编码后由128维GRU汇总；每个窗口重置隐藏状态，不能当作整段持续记忆。
训练输入包含两路视觉、触觉及状态。每100步在完整训练/验证集评估，保存history.json。
last.pt为2000步最终模型；best.pt按验证归一化MSE选择，验证不再是独立测试。
history_index.npz保存逐样本历史索引和缺失位置。

训练完成后画图：

```bash
/usr/bin/python3 scripts/plot_eef_history.py local/eef_history/oct03_run1
```

learning_curves.png为训练与验证曲线；validation_episode_0/1.png分别是bag_002/008验证预测。

本轮已完成：最终验证1.011mm/0.004215rad，最优100步0.907mm/0.003405rad。
不能将最优100步与单帧2000步的差异直接归因于历史；结果与过拟合问题见
[历史训练编年](../docs/agent/training/chronicles/2026-10-03-history-gru-training.md)。
