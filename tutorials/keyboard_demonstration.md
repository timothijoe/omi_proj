# 键盘录制 A 臂示范

前提：MuJoCo 场景已通过预检。此命令**只控制仿真 A 臂**，会创建或覆盖指定 JSONL 文件；请选择新文件名保留旧录制。

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.sim.keyboard_teleop --scene "$SCENE" \
  --output data/demonstrations/my_keyboard.jsonl
```

输入 `1+`、`1-` 到 `7+`、`7-` 并回车，分别让一个关节正向或负向前进一步；空回车保持，`r` 复位，`q` 退出。终端显示关节角与 TCP 距离，成功或超时后自动开启下一回合。退出后校验：

```bash
.venv/bin/python -m omi_hil_rl.training.validate_recording data/demonstrations/my_keyboard.jsonl
```

若录制为空，校验会报错；至少执行一个有效点动再退出。键盘操作本身尚未做人工可用性验收；当前只验证了命令解析和记录数据链。
