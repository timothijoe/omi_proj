# OMI：天机机械臂 Human-in-the-Loop RL

ROS采集与新看板：[传感器教程](tutorials/sensor_collection.md) · [SDK原生看板](tutorials/sdk_native_dashboard.md)。
换机器前必看：[额外拷贝/重新安装清单](tutorials/machine_transfer_checklist.md)；Git不包含SDK、bag、基准和模型资源。

本项目的目标是在**天机 Marvin 机械臂**上建立真实机器 Human-in-the-Loop 强化学习系统。正式代码、设备适配、任务配置、数据与实验记录统一放在 `omi_proj/`。参考项目保留在兄弟目录：`hil_serl_projects/` 提供 HIL-SERL 与 LeRobot 实现，`cooking_proj/` 提供天机实机控制经验，`TJ_FX_ROBOT_CONTRL_SDK/` 提供厂商 SDK。

已选定 **SDK A 臂（左臂）**，首个任务是 MuJoCo 中的末端定点到达，遥操作初始化采用终端键盘逐关节点动。天机场景来自 `cooking_proj` 的外部本地资产。先看 [工作区总索引](../README.md)、[文档总目录](docs/README.md)、[能力总表](docs/capabilities.md) 和 [操作教程](tutorials/README.md)；[HIL RL 四项复现审计](docs/hil_rl_reproduction.md)明确训练、干预、buffer 与策略改善的证据和缺口。旧的自包含七关节代理环境只用于接口单元测试。项目尚未连接或驱动真机。

运行无硬件仿真测试：

```bash
cd omi_proj
bash scripts/setup_sim.sh
source scripts/env.sh
python -m pytest -q
python -m omi_hil_rl.sim.smoke
```

运行带脚本接管的 A 臂 SAC 训练试验（CPU 版 PyTorch；输出到忽略版本控制的 `data/`）：

```bash
source scripts/env.sh
SCENE="$OMI_TIANJI_SCENE"
.venv/bin/python -m omi_hil_rl.sim.preflight --scene "$SCENE"
.venv/bin/python -m omi_hil_rl.training.sim_train --scene "$SCENE" --steps 1500
.venv/bin/python -m omi_hil_rl.training.validate_recording data/sim_runs/latest/transitions.jsonl
.venv/bin/python -m omi_hil_rl.training.sim_eval data/sim_runs/latest/policy.zip --scene "$SCENE" --episodes 10
MUJOCO_GL=egl .venv/bin/python -m omi_hil_rl.sim.visualize --scene "$SCENE" \
  --checkpoint data/sim_runs/latest/policy.zip
```

训练脚本会保存策略、经验池、逐步 transition 和评估指标。训练时的自动“接管”由脚本教师模拟；真人键盘示范可通过 `sim.keyboard_teleop` 录制，再用 `--demo-recording` 导入经验池。SAC 训练层用 Stable-Baselines3 做仿真验证，实机阶段仍计划以 LeRobot HIL-SERL 为主训练基础。

当前 A 臂 MJCF 任务训练 1500 步后，在独立的 30 个随机初始状态评估回合中全部成功。这个结果只证明简单仿真任务的闭环，不预测真机效果。仓库提供 [静态验证图](docs/evidence/a_reach_policy.png) 和 [MuJoCo 动画](docs/evidence/a_reach_policy.gif)。

下一阶段需在现场核对模型与 A 臂关节、TCP 和工具，完成只读反馈、受限控制、相机时间同步和真人示范验收，再接入 LeRobot 的 SAC actor/learner。
