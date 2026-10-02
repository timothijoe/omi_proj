# 2026-10-01：OMI 本地仿真环境配置

**环境：**Linux x86_64、Python 3.12.3；项目独立 `.venv`。MuJoCo 3.14.0、Gymnasium 1.3.0、PyTorch 2.14.1+cpu、Stable-Baselines3 2.9.0。30 个依赖固定在 `requirements/simulation.lock.txt`；`bash scripts/setup_sim.sh` 安装依赖和 OMI 源码，重复执行通过，`pip check` 无依赖冲突。

**资源：**从 `/home/zhoutong/sep_folder/cooking_proj/local/assets` 复制 `robot_assets` 和 `MarvinCCS` 到 OMI 的 `local/assets`，保留原始文件。来源和场景 SHA256 存在本地 `provenance.json`。`source scripts/env.sh` 激活环境、配置场景与 EGL，并隔离终端继承的 ROS Python 路径。激活已在项目外目录验证。

**验证：**配置本地 MJCF 后自动测试 26 passed，没有跳过外部模型测试；A 臂七关节、执行器、掌心 TCP 预检通过。EGL 教师回合 6 步成功，TCP 误差 0.319 m → 0.025 m，已生成 PNG/GIF。

**训练：**本环境以种子 0 跑 1500 步低熵纯 SAC，`bc_weight=0`、初始熵系数 0.01；前 500 步教师示范，后续接管概率 0.2。1400 次 SAC 更新、0 次 BC 更新；709 条干预进入示范流，1500 条记录校验通过。固定 10 回合无接管评估从 0/10 到 10/10；种子 2000 起的独立 30 回合为 30/30，平均 6.03 步、终点误差 0.0167 m。训练策略的渲染回合 6 步成功，终点误差 0.0136 m。

**产物：**`data/environment_setup/preflight.json`、`teacher/`、`sac_seed0/`、`policy/`，均忽略版本控制。可按 [环境教程](../../../../tutorials/environment_setup.md)激活，再用下列命令复现训练；换输出目录可保留本次结果。

```bash
python -m omi_hil_rl.training.sim_train --scene "$OMI_TIANJI_SCENE" \
  --steps 1500 --demonstration-steps 500 \
  --later-intervention-probability 0.2 --evaluation-episodes 10 \
  --bc-weight 0 --entropy-initial 0.01 --seed 0 \
  --output-dir data/sim_runs/my_sac_seed0
```

**边界：**以上是固定目标 A 臂仿真验证，训练有脚本示范和接管。当前 NVIDIA 驱动查询不可用，训练使用 CPU，EGL 离屏渲染实际通过；没有 GUI 交互验收。本轮未连接硬件，也未接入 LeRobot 分布式训练。SDK 路径默认指向兄弟目录，真机阶段继续在 OMI 中单独验收设备配置与反馈。
