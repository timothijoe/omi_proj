# A 臂任务、训练与独立评估

前提：完成 [最短案例](quickstart.md)，安装训练依赖。以下训练会在 `data/sim_runs/` 写检查点、回放和逐步记录；用新输出目录避免覆盖旧结果。

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.training.sim_train --scene "$SCENE" \
  --steps 1500 --demonstration-steps 500 \
  --later-intervention-probability 0.2 --evaluation-episodes 10 \
  --output-dir data/sim_runs/my_a_reach --seed 0
.venv/bin/python -m omi_hil_rl.training.validate_recording \
  data/sim_runs/my_a_reach/transitions.jsonl
.venv/bin/python -m omi_hil_rl.training.sim_eval \
  data/sim_runs/my_a_reach/policy.zip --scene "$SCENE" --episodes 30 --seed 2000
```

训练打印步数、接管数和无接管评估成功率。校验器打印 transition、接管和结束回合数量；评估器重新运行环境。`Ctrl+C` 可以停止训练，但不保证生成完整检查点；请另选输出目录重新运行。已有一次实验为 30/30，详见 [证据报告](../docs/a_arm_reach.md)；这不是每台机器的预期保证。生成策略 GIF 见 [录制与可视化](recording_and_replay.md)。

训练还保存 `policy_progress.jsonl` 和周期 `policy_step_*.zip`。用固定种子无干预评估绘图：

```bash
.venv/bin/python -m omi_hil_rl.training.plot_progress \
  data/sim_runs/my_a_reach/policy_progress.jsonl \
  data/sim_runs/my_a_reach/policy_progress.png
```

`--bc-weight 0` 可运行只含 SAC 更新的对照。要复现已验证的纯 SAC 策略改善，用 `--bc-weight 0 --entropy-initial 0.01`，其余参数沿用上面的 1500 步命令并指定新输出目录。该设置在 10 个固定种子回合从 0/10 到 10/10，另取 30 回合为 30/30；默认初始熵系数 1.0 的纯 SAC 在 1500 与 5000 步都失败。对照和限制见 [四项审计](../docs/hil_rl_reproduction.md)。
