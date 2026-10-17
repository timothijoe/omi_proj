# Ubuntu 22.04：在线 RL 与人工回合采集的运行依赖

本文只补充已经能启动的传感器、机器人接收端之外，OMI 两个入口所需的环境：

| 入口 | Python 路径 | 用途 |
| --- | --- | --- |
| `bash scripts/collect_rl_episodes.sh` | `.venv/bin/python` | 手柄人工回合采集、ROS 观测、动作回执及数据落盘 |
| `bash scripts/run_async_rl.sh` | `local/cuda-env/bin/python` | 在线 Actor、后台 Learner、GPU 推理和训练 |

两个入口都会调用 `scripts/env_ros.sh`，默认寻找 **Jazzy**。在 22.04 上需先设置 `OMI_ROS_DISTRO=humble`。脚本会从 ROS overlay 加载 `rclpy` 和消息类型；训练依赖装在另一个 Python 环境里，并不能代替 ROS 的二进制扩展。

## 必需依赖

| 类别 | 两个入口所需内容 | 来源 |
| --- | --- | --- |
| 项目 Python | `omi-hil-rl`、NumPy、Gymnasium、PyTorch | `pyproject.toml` 的基础依赖与 `bc` extra；当前项目声明 Python **>=3.12** |
| ROS Python | `rclpy`、`sensor_msgs`、`geometry_msgs`、`std_msgs`、`std_srvs` | 与运行解释器 ABI 匹配的 ROS Humble 安装 |
| 手柄 | 可读的 `/dev/input/js0`，具备摇杆、十字键、RB 和回合按键 | Linux 设备节点；读取器使用标准库 `fcntl`，无需另装手柄 Python 包 |
| 在线训练 | 可用的 NVIDIA 驱动、支持该 GPU/驱动的 CUDA 版 PyTorch | [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/)；脚本默认从 `local/cuda-env` 运行 |
| 夹爪 | `dm_lingkong_grip_sdk` 及厂商要求的 `grpcio`、`protobuf` 等 | 两个入口执行模式下默认启用；不使用夹爪时传 `--no-gripper` |

采集入口虽不训练网络，代码仍会导入 `torch` 和 `gymnasium`，因此 `.venv` 不能只有 `rclpy`。在线入口的 Actor 和 Learner 使用同一个 `local/cuda-env/bin/python`；该解释器也必须能导入 ROS Python 包。只检查 `torch.cuda.is_available()` 不足以证明在线入口可用。

## 22.04 / Humble 的版本关口

Ubuntu 22.04 的常规 Humble 安装使用系统 Python 3.10；当前 OMI 包要求 Python >=3.12，而上述两个脚本分别固定调用项目 `.venv` 和 `local/cuda-env`。直接把 Humble 的 Python 3.10 `rclpy` 路径加入 Python 3.12 的 `PYTHONPATH`，不能使二进制扩展兼容。因此，**现有脚本不能仅靠增加 pip 包就在标准 22.04/Humble 环境运行**。

如果这台机器已经有一个能同时导入 OMI、ROS 消息和 CUDA PyTorch 的解释器，请用下节逐项检查，再将它部署到脚本固定的两个路径。否则需先完成并验证一种兼容方案：把 OMI 在线代码及包约束适配到 Python 3.10，或者为 Python 3.12 构建匹配的 ROS Python/消息 overlay。当前仓库没有提供这两种方案的已验收安装脚本；不要用 `--ignore-requires-python` 或跨版本复制 `site-packages` 绕过检查。[Humble 安装说明](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)与 [PyTorch CUDA 选择器](https://pytorch.org/get-started/locally/)用于核对目标机实际版本。

## 安装与预检顺序

在项目根目录、干净的 Bash 终端执行。下面的安装命令适用于**已经解决上述 Python/ROS ABI 匹配**的环境；若尚未解决，应先运行版本检查，不要启动 `--execute`。

```bash
cd /path/to/omi_proj
export OMI_ROS_DISTRO=humble

python3 --version
.venv/bin/python --version
local/cuda-env/bin/python --version
test -f /opt/ros/humble/setup.bash
```

项目包和普通 Python 依赖安装到**两个脚本各自使用的解释器**。已有环境满足依赖时可跳过安装；不要把 CPU 版 PyTorch 装到在线 CUDA 环境里。

```bash
.venv/bin/python -m pip install -e '.[bc,ros]'
local/cuda-env/bin/python -m pip install -e '.[bc,ros]'
.venv/bin/python -m pip check
local/cuda-env/bin/python -m pip check
```

在线环境的 CUDA PyTorch 应先按目标 GPU 和驱动从[官方命令](https://pytorch.org/get-started/locally/)安装，再执行上面的 editable install；不要照搬原机器的 `local/cuda-env` 或本机 CUDA 13.0 wheel。若只建立人工采集环境，`.venv` 的 CPU PyTorch 即可。默认启用夹爪时，还需按现场厂商 SDK 的版本安装其依赖，并确认 `dm_lingkong_grip_sdk` 可以被采集/在线入口所用解释器导入；不使用夹爪时在运行命令加 `--no-gripper`。

分别检查**实际入口解释器**，不能只用系统 `python3` 检查：

```bash
source scripts/env_ros.sh
.venv/bin/python -c 'import sys, numpy, gymnasium, torch, rclpy; from sensor_msgs.msg import Image; from geometry_msgs.msg import PoseStamped; from std_msgs.msg import Float64MultiArray, String; from std_srvs.srv import Trigger; print(sys.version, torch.__version__, rclpy.__file__)'
local/cuda-env/bin/python -c 'import sys, torch, rclpy; print(sys.version, torch.__version__, torch.version.cuda, torch.cuda.is_available(), rclpy.__file__)'
.venv/bin/python -m omi_hil_rl.hil.collect_episodes --help
local/cuda-env/bin/python -m omi_hil_rl.hil.async_training --help
```

`torch.cuda.is_available()` 对 GPU 在线训练应为 `True`。两个 `--help` 只检查入口能加载，不能验证 ROS 话题、手柄、回执或真机动作。`source scripts/env_ros.sh` 会激活 `.venv`，也可能自动加载 `local/ros2/marvin_msgs_ws` 中的旧消息 overlay。当前 RL 观测不读取 `marvin_msgs` 关节反馈；若现场另需此消息类型，应将 `OMI_MARVIN_MSGS_SETUP` 显式指向与接收端匹配的 overlay，避免同名旧定义覆盖现场版本。

预检通过后，使用[人工采集教程](rl_episode_collection.md)和[当前在线 RL 命令](common_live_commands.md#rl-start)中的参数启动。采集输出目录与在线任务目录要放在可写且空间充足的本地盘；继续旧任务时复制完整任务目录和原始回合，不只复制 `actor.pt`。这两个动作入口一次只运行一个。
