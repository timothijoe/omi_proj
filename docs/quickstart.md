# 开发最短入口

从 `omi_proj/` 根目录运行，先完成 [环境重建](../tutorials/environment_setup.md)。激活脚本使用本地恢复的模型；可在激活前通过 `OMI_TIANJI_SCENE` 指定外部资源。

```bash
source scripts/env.sh
python -m omi_hil_rl.sim.preflight --scene "$OMI_TIANJI_SCENE"
python -m omi_hil_rl.sim.visualize --scene "$OMI_TIANJI_SCENE"
```

预期得到 A 臂关节与目标报告，以及 `data/visualizations/a_reach/` 下的 GIF、PNG、JSON。脚本教师的可视化只能说明场景与动作链可运行。完整训练见 [A 臂训练教程](../tutorials/a_arm_simulation.md)，实现机制见 [训练纪传体](agent/training/evolution/hil-training.md)。缺少 MJCF 时可运行无外部资源的 `python -m omi_hil_rl.sim.smoke`。
