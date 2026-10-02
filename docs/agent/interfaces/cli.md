# CLI 入口

从 `omi_proj/` 使用 `source scripts/env.sh` 激活环境。下表均是 `python -m` 模块入口，不是安装后自动生成的可执行命令，也不是 Shell 脚本。路径相对 `omi_proj/` 工作目录解析。

| 模块 | 必要参数 | 作用 | 副作用 |
| --- | --- | --- | --- |
| `omi_hil_rl.sim.preflight` | `--scene PATH` | 编译场景并报告 A 臂任务 | 可选 `--output` 写 JSON |
| `omi_hil_rl.sim.keyboard_teleop` | `--scene PATH` | 终端逐关节点动 | `--output` 写/覆盖 JSONL |
| `omi_hil_rl.sim.interactive_rollout` | `CHECKPOINT --scene PATH` | 运行策略并允许逐步键盘覆盖 | `--output` 写/覆盖 JSONL |
| `omi_hil_rl.training.sim_train` | 无；A 臂需 `--scene PATH` | SAC 仿真训练 | `--output-dir` 写模型、回放、日志 |
| `omi_hil_rl.training.replay_benchmark` | `--directory PATH`（空目录） | 三路 RGB 磁盘写入和缓存采样基准 | 写 `.npy`、manifest 与结果 JSON |
| `omi_hil_rl.real.tactile_baseline` | `BAG OUTPUT_DIR`；可选 `--start-s/--end-s` | 从已确认无接触窗口生成双指 raw 基准并校验 depth/wrench | 只读 bag；新建本地基准目录，拒绝覆盖 |
| `omi_hil_rl.real.tactile_offline` | `BAG BASELINE_DIR OUTPUT_DIR --sdk-root PATH` | 无设备连接地重建选定时刻 deformation/shear/depth 和 dashboard | 只读 bag/SDK；新建本地结果目录，拒绝覆盖 |
| `omi_hil_rl.training.validate_recording` | `RECORDING` | 校验 JSONL | 只读 |
| `omi_hil_rl.training.sim_eval` | `CHECKPOINT`；A 臂需 `--scene PATH` | 无接管评估 | 只读模型、运行仿真 |
| `omi_hil_rl.sim.visualize` | `--scene PATH` | 教师或 `--checkpoint` 策略渲染 | `--output-dir` 写 PNG/GIF/JSON |
| `omi_hil_rl.training.plot_progress` | `PROGRESS OUTPUT` | 绘制固定种子评估曲线 | 写 PNG |
| `omi_hil_rl.sim.smoke` | 无 | 代理模型快速回合 | 控制台输出 |

训练可附加 `--demo-recording PATH` 导入真人格式的示范；默认不导入。每个模块的完整参数以 `python -m <模块> --help` 为准。没有真机 CLI；不要把仿真命令指向 SDK 控制器。

`sim_train` 用 `--demonstration-steps` / `--later-intervention-probability` 控制脚本接管，用 `--bc-weight` 控制额外行为克隆，用 `--entropy-initial` 控制自动温度初值。CLI 默认 BC 权重 10、初始熵 1.0；已验证的低熵纯 SAC 命令显式指定 0 / 0.01。训练和评估选择 A 臂都必须传 `--scene`，仅设置环境变量不会改变它们的默认代理任务。奖励模式和 `demo_fraction=0.5` 由训练代码设置，没有对应 CLI 参数。机制见 [训练纪传体](../training/evolution/hil-training.md)。

Shell 入口：`bash scripts/setup_sim.sh` 安装固定依赖和 OMI 源码；`source scripts/env.sh` 激活项目环境、配置资源路径并隔离 ROS Python 路径。它们不会连接设备。完整步骤见 [环境教程](../../../tutorials/environment_setup.md)。

`tactile_baseline` 运行前使用 `source scripts/env_ros.sh`。它只读 bag，不播放 topic、不连接
设备，也不发布控制消息。`--serial-a/--serial-b` 只能填写已经由设备或录制元数据确认的
厂商序列号；未知时保持为空，不能根据日志文件名猜测 A/B 映射。

`tactile_offline` 不创建厂商 `Sensor`，仅使用底层 CPU 算法类，因此不要求 serial，也不
枚举或连接设备。默认探测 23、25.5、28 秒；可重复传入 `--target-s` 改变时刻。它要求
独立环境包含 `h5py`，并通过 `--sdk-root` 指向包含 `dmrobotics/` 的 SDK 目录。

`sim_train --replay-backend {memory,disk}` 默认 memory；`--replay-capacity N` 固定 ring 容量，`--replay-directory PATH` 指定磁盘目录（默认输出目录下 `replay/`），`--no-replay-prefetch` 关闭后台 batch 预取。创建不覆盖已有磁盘目录；恢复通过 Python API，没有完整 CLI 续训。详见 [教程](../../../tutorials/disk_replay.md)。
