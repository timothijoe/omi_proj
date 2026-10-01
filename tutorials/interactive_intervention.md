# 策略运行中的键盘干预

前提：按 [A 臂训练教程](a_arm_simulation.md)取得 `policy.zip`，外部场景已通过预检。本入口逐步运行 MuJoCo 策略，输出文件为 JSONL；请选择新文件名以保留旧录制。

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.sim.interactive_rollout \
  data/sim_runs/my_a_reach/policy.zip --scene "$SCENE" \
  --output data/demonstrations/my_intervention.jsonl
```

每一步终端先显示策略建议和 TCP 距离。直接回车执行策略；输入 `1+..7-` 并回车则用所选关节的一步点动覆盖策略；`h` 为人工保持，`r` 复位，`q` 退出。输出显示实际命令及来源。录制后运行：

```bash
.venv/bin/python -m omi_hil_rl.training.validate_recording \
  data/demonstrations/my_intervention.jsonl
```

这是终端逐步式仿真干预，会等待输入；不具备真实时间的连续接管性能。`Ctrl+C` 可停止。`--output` 会创建或覆盖同名文件。记录中的 `human` transition 可通过 `--demo-recording` 导入后续训练。
