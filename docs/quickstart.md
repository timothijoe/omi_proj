# 开发最短入口

从仓库根目录运行，先完成 [环境重建](../tutorials/environment_setup.md)。外部场景资源路径由操作者设置，不写死在仓库中。

```bash
SCENE=/path/to/cooking_proj/local/assets/robot_assets/mujoco/right_chopping_scene.xml
.venv/bin/python -m omi_hil_rl.sim.preflight --scene "$SCENE"
.venv/bin/python -m omi_hil_rl.sim.visualize --scene "$SCENE"
```

预期得到 A 臂关节与目标报告，以及 `data/visualizations/a_reach/` 下的 GIF、PNG、JSON。脚本教师的可视化只能说明场景与动作链可运行。完整训练见 [最短仿真案例](../tutorials/quickstart.md)。缺少 MJCF 时可运行无外部资源的 `python -m omi_hil_rl.sim.smoke`。
