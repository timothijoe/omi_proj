# 仿真环境安装与激活

从 `omi_proj/` 执行，使用 Linux x86_64、Python 3.12 和 Bash。当前本机环境已经安装；日常使用只需激活：

```bash
cd omi_proj
source scripts/env.sh
```

脚本激活项目 `.venv`，配置本地 A 臂场景 `OMI_TIANJI_SCENE` 和离屏渲染后端 `MUJOCO_GL=egl`。它会清除当前终端继承的 `PYTHONPATH`，避免系统 ROS 包混入项目环境。需要运行 ROS 工具时使用另一个终端。激活脚本不连接设备。

## 重建 Python 环境

```bash
bash scripts/setup_sim.sh
source scripts/env.sh
python -m pip check
```

安装脚本使用 Python 自带的 venv/pip，无需 uv；通过 `requirements/simulation.lock.txt` 安装固定版本的 MuJoCo、Gymnasium、CPU PyTorch、SB3、测试和图像依赖，再安装 OMI 源码。下载需要网络，缓存放在 `local/pip-cache/`。可用 `OMI_PYTHON=/path/to/python3.12 bash scripts/setup_sim.sh` 指定解释器。

## 模型资源

本机已恢复 `local/assets/robot_assets/` 与 `local/assets/MarvinCCS/`，场景包括机械臂和灵巧手。资源来源与场景 SHA256 记录在 `local/assets/provenance.json`。模型、虚拟环境与生成数据均不进入 Git。

换机器时需恢复完整资源树，保持这两个目录相邻。若已有外部资源，可在激活前指定：

```bash
export OMI_TIANJI_SCENE=/path/to/assets/robot_assets/mujoco/right_chopping_scene.xml
source scripts/env.sh
```

## 检查仿真

```bash
python -m pytest -q
python -m omi_hil_rl.sim.preflight --scene "$OMI_TIANJI_SCENE"
python -m omi_hil_rl.sim.visualize --scene "$OMI_TIANJI_SCENE" \
  --output-dir data/visualizations/my_teacher
```

配置场景后，外部 MJCF 测试也会运行。可视化输出 `episode.gif`、`reach_verification.png` 和 `metrics.json`。这是脚本教师回合，训练策略按 [A 臂教程](a_arm_simulation.md)运行。缺模型时仍能用 `python -m omi_hil_rl.sim.smoke` 检查代理环境。

## 后续真机实验

真机适配代码、现场配置和实验数据继续放在 OMI。激活脚本中的 `OMI_TIANJI_SDK_ROOT` 默认指向兄弟目录 `TJ_FX_ROBOT_CONTRL_SDK`；它只是路径约定，不会自动读取该变量或创建硬件对象。配置适配器时，需显式将该路径传给 `TianjiConfig.sdk_root`，即包含 `SDK_PYTHON` 的目录。

当前已验证的是仿真环境。SDK 与控制器版本、现场关节限位、工具 TCP、反馈和停止行为仍按 [真机准备](hardware_preflight.md)另行验收。当前环境不包含 LeRobot 分布式训练或 ROS 集成。
