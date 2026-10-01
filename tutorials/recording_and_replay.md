# 录制、示范导入与可视化

`keyboard_teleop` 的 JSONL 可以预填训练经验池。先运行 [键盘示范](keyboard_demonstration.md) 并校验文件，再执行：

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.training.sim_train --scene "$SCENE" \
  --demo-recording data/demonstrations/my_keyboard.jsonl \
  --steps 1500 --output-dir data/sim_runs/with_keyboard
MUJOCO_GL=egl .venv/bin/python -m omi_hil_rl.sim.visualize --scene "$SCENE" \
  --checkpoint data/sim_runs/with_keyboard/policy.zip \
  --output-dir data/visualizations/with_keyboard
```

训练指标中的 `imported_human_demonstrations` 应大于零；否则检查记录是否包含 `action_source=human`。导入会验证模型类型和观测空间，不能把代理任务或另一场景的状态混入 A 臂训练。可视化输出 GIF、PNG、JSON；`Ctrl+C` 可中断渲染，但可能留下未完成文件。当前没有轨迹“回放到实机”的入口，`replay.pkl` 是训练经验池快照。
