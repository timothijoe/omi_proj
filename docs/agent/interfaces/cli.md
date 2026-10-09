# CLI 入口

固定BC评估：`bash scripts/run_bc_episodes.sh --output SESSION --resume --control-mode periodic --episodes 1 --execute`。
最新已准备SESSION为`local/bc_episodes/all8_coarse_fine_eval_01`（11795）；无Learner。
默认periodic是100ms目标发布+独立审计，不逐条等待回执；审计不自动入训练池，receipt模式才用旧同步配对。
成功动作label回放：`bash scripts/replay_success_episode.sh --episode EPISODE`默认只读；
`--output NEW_DIR --execute`才启用真机，315开始、RB取消回放并接管，不加载神经网络。
全8回合拟合：`python -m omi_hil_rl.hil.fit_all_bc --checkpoint BC_PT --output NEW_DIR [--prepare-output NEW_SESSION]`，
仅离线，所有8回合用于训练，无独立验证成绩。详见[操作教程](../../../tutorials/bc_replay_testing.md)
和[实现记录](../training/chronicles/2026-10-07-periodic-replay-bc-fitting.md)。

异步真机RL：`bash scripts/run_async_rl.sh --run RUN --execute [--enable-policy]`。
最新双池RUN：`local/rl_training/bc_protected_dual_20261007_01`。
新建保护式双池：`bash scripts/prepare_bc_rl.sh --bc-run BC_DIR --run NEW_RUN --capacity 4000 --intervention-capacity 2000`。
旧单池离线迁移：`bash scripts/migrate_dual_replay.sh --source OLD_RUN --run NEW_RUN --intervention-capacity 2000`，
要求源会话已停止，拒绝覆盖目标或迁移dirty池；旧目录保留。
一条命令同时启动Actor/手柄采集与独立Learner子进程；默认人工，加`--enable-policy`才允许模型动作。
每10个完整有效回合检查最新有效权重；Learner达到数据门槛后持续训练，不等回合交替。
Ctrl+C关闭本次Actor/采集/训练，不关闭外部传感器、控制接收端或RViz。
现场需提前启动传感器和接收端，不要并开其他动作发布者。
准备/并发无机器人验证参数与限制见[异步RL教程](../../../tutorials/async_rl.md)。

wrench看板及历史录制：`bash scripts/view_wrench_live.sh [--window 15] [--duration SECONDS] [--no-rviz]`；
本地全程图重建：`--review-session SESSION`。默认domain13，只订阅传感器并发布诊断图；
逐条记录保存至local/wrench_live新会话。[教程](../../../tutorials/wrench_live.md)。

只读触觉预警：`bash scripts/watch_tactile_warning.sh --force-limit VALUE --torque-limit VALUE`，
至少指定一种阈值；默认domain13，直接比较原始三维力/力矩模长，超限打印WARNING。
不扣基线、不锁定、不发布动作、不改变保护开关；可加 `--log-file NEW_FILE` 保存日志。
详见[教程](../../../tutorials/tactile_warning.md)。

控制端本地构建/离线预览：`bash scripts/robot_controller.sh {build|preview}`；原包导入/校验：`python3 scripts/import_optical_module.py {import ZIP|verify}`。见[教程](../../../tutorials/robot_controller.md)。

接收端[触觉保护](../../../tutorials/tactile_guard.md)默认关闭，显式开启只影响模型通道；
手动通道 `manual_delta_topic` 默认 `/omi/action/manual_decision`，不参与触觉拦截。
`/delta_ctrl_node/capture_tactile_baseline`、`/delta_ctrl_node/reset_tactile_guard`
均为 `std_srvs/srv/Trigger`，显式解除启动阻塞/触发锁定；
`/omi/safety/tactile_guard` 为 `std_msgs/msg/String` JSON 状态。
launch 可配置 `tactile_guard_enabled`、`tactile_force_limit`、`tactile_torque_limit`、
`tactile_timeout`、`tactile_retreat_step_mm`、`tactile_retreat_speed_mm_s`。

`eef_bc.sh export --wrist-camera {off,required,optional}`启用EEF v2相机配置，省略保持v1。
train/shadow自动读取已保存的输入源契约，不接受静默切换相机；[用法](../../../tutorials/eef_action_space.md#6-开启或关闭腕部相机v2)。

末端动作实验：`bash scripts/eef_bc.sh {export|train|shadow} --help`。
export需`--accept-future-state-proxy`，train需独立episode或`--overfit-smoke`，shadow使用
已构建的omi_action_msgs，默认localhost domain92，仅发布类型化候选。
[构建及完整命令](../../../tutorials/eef_action_space.md)。

当前Stand模型对照使用：

```bash
bash scripts/view_corrected_stand_observation_3d.sh ZIP_OR_BAG MODEL.rar [RATE=1] [--no-rviz]
```

固定localhost domain94，仅回放显示；左3/4/6、右3/4/5关节方向重参数化。
同参数的 `view_stand_observation_3d.sh`（domain98）保留未修正角度定义，
`view_hybrid_observation_3d.sh`（domain95）保留旧链并配准部分网格。
这些是Shell脚本，不是已安装的ROS控制节点入口。
调用`--help`不加载模型或连接设备；正常运行只发布显示topic。
关节限位、base/TCP未验收；[版本选择和限制](../hardware/evolution/robot-3d-replay.md#入口选择与当前结论)。

录包BC实验：`bash scripts/bag_bc.sh {export|train|shadow} --help`，分别调用
training.bag_bc_data、bc_policy、bc_shadow；Jazzy与匹配Marvin消息，默认localhost domain99。
export要求显式动作语义假设；train要求独立验证episode或overfit-smoke；shadow只输出JSON，
没有实际控制接口。输出目录拒绝覆盖。见[教程](../../../tutorials/bag_bc_shadow.md)。

SDK原生看板：`bash scripts/view_sdk_observation.sh [--fake | --bag BAG] [--config FILE] [--no-rviz]`。
不带数据源参数时只订阅已有流，不启动硬件；默认domain88。安装后可用 `omi-sdk-view`。
只启动发布看板节点：`python3 -m omi_sensors.cli --config FILE dashboard`。
输出 `/omi/sdk/dashboard`，不重建字段；[完整说明](../../../tutorials/sdk_native_dashboard.md)。

稳定合并看板仍用 `view_observation_bag.sh`，迁移版必须显式使用
`view_observation_bag_migrated.sh`（纯触觉对应 `view_tactile_bag_migrated.sh`）。
迁移版内部模块为 `omi_hil_rl.real.tactile_live_migrated`；两版不要在同一domain同时运行。
新版SDK到RL的实现状态见[集成方案](../../design/ros-to-policy-integration.md)。

独立传感器包：`python3 -m omi_sensors.cli --config FILE {plan,doctor,live,fake,record,replay}`。
先 source colcon overlay；不依赖主 RL Python 环境。安装入口 `bash scripts/setup_sensors.sh`，
显式 `--install-system` 才调用 apt。详细参数/作用及双系统边界见
[传感器教程](../../../tutorials/sensor_collection.md)和[接口契约](../hardware/evolution/sensor-collection.md)。
`live` 会连接相机/触觉设备，但不启动机械臂/夹爪控制；其余入口不连接硬件。

合并相机与触觉：`bash scripts/view_observation_bag.sh BAG [RATE] [--no-rviz]`。
它对缓存生成器和 dashboard 传入 `--with-cameras`，使用同一播放器回放四路传感器。
显示 topic 为 `/omi/observation/dashboard`；纯触觉入口继续保留。

触觉回放新入口：`bash scripts/view_tactile_bag.sh BAG [RATE] [--no-rviz]`。
它调用 `python -m omi_hil_rl.real.tactile_replay_cache BAG CACHE_ROOT` 创建独立 raw 缓存，
默认工作路径 `local/tactile/replay_cache` 自 2026-10-09 起经软链接读取外盘，须挂载移动盘；
位置与恢复边界见[存储契约](local-storage.md)。
并启动 `python -m omi_hil_rl.real.tactile_live fields --baseline-dir DIR --sdk-root DIR`
和独立的 `...tactile_live dashboard`。两进程支持 `--rate`；仅发布触觉数值/显示消息，
不发布控制命令。[数据契约及限制](../hardware/evolution/tactile-live.md)。

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
