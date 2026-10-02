# A 臂任务、训练与独立评估

需要将回放写入磁盘时，使用 `--replay-backend disk --replay-capacity N`，完整参数、产物与恢复见 [磁盘回放教程](disk_replay.md)。默认仍为内存池。

前提：完成 [最短案例](quickstart.md)，安装训练依赖。从 `omi_proj/` 执行。以下是已在本机验证的低熵纯 SAC 配置，会在 `data/sim_runs/` 写检查点、回放和逐步记录；用新输出目录避免覆盖旧结果。

```bash
source scripts/env.sh
python -m omi_hil_rl.training.sim_train --scene "$OMI_TIANJI_SCENE" \
  --steps 1500 --demonstration-steps 500 \
  --later-intervention-probability 0.2 --evaluation-episodes 10 \
  --bc-weight 0 --entropy-initial 0.01 \
  --output-dir data/sim_runs/my_a_reach --seed 0
python -m omi_hil_rl.training.validate_recording \
  data/sim_runs/my_a_reach/transitions.jsonl
python -m omi_hil_rl.training.sim_eval \
  data/sim_runs/my_a_reach/policy.zip --scene "$OMI_TIANJI_SCENE" --episodes 30 --seed 2000
```

训练使用脚本教师：前 500 步全部接管，之后接管概率为 0.2。它不读取真人键盘输入。训练打印步数、接管数和无接管评估成功率；本配置应显示 `bc_updates=0`。校验器打印 transition、接管和结束回合数量；评估器重新运行环境。`Ctrl+C` 可以停止训练，但不保证生成完整检查点；请另选输出目录重新运行。最近本机复验为 30/30，详见 [环境证据](../docs/agent/simulation/chronicles/2026-10-01-omi-environment.md)；这不是每次实验的保证。生成策略 GIF 见 [录制与可视化](recording_and_replay.md)，真人覆盖操作见 [交互接管](interactive_intervention.md)。

训练还保存 `policy_progress.jsonl` 和周期 `policy_step_*.zip`。用固定种子无干预评估绘图：

```bash
python -m omi_hil_rl.training.plot_progress \
  data/sim_runs/my_a_reach/policy_progress.jsonl \
  data/sim_runs/my_a_reach/policy_progress.png
```

上面的命令显式关闭额外 BC 更新，仍使用教师经验。CLI 默认 `bc_weight=10`、`entropy_initial=1.0`；若要运行此前的 SAC+BC 组合配置，将这两个参数改为 `--bc-weight 10 --entropy-initial 1.0` 并指定新输出目录。默认熵纯 SAC 曾在 1500 与 5000 步失败。对照和限制见 [四项审计](../docs/hil_rl_reproduction.md)。训练的进度奖励与评估的稀疏奖励不同，不要直接比较两者回报。
