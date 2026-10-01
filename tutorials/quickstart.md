# 最短可运行仿真案例

前提：完成 [环境安装](environment_setup.md)，并恢复 [模型资源](../manifests/resources.yaml)。从仓库根目录运行：

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.sim.preflight --scene "$SCENE"
MUJOCO_GL=egl .venv/bin/python -m omi_hil_rl.sim.visualize --scene "$SCENE"
```

预检应打印 A 臂七关节、目标 TCP 和控制周期；可视化使用脚本教师，输出 `data/visualizations/a_reach/episode.gif`、`reach_verification.png` 和 `metrics.json`。看到 `success: true` 说明此场景的教师回合完成；它不代表策略已训练。查看图片后结束即可，无后台进程。若 EGL 不可用见 [排障](troubleshooting.md)。
