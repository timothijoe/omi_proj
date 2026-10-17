# 真机常用启动指令汇总

以下命令均在 `/home/zhoutong/omi_folder/omi_proj` 执行。每个持续运行的命令占用一个终端；保留其终端运行，按 `Ctrl+C` 停止。本页汇总现场常用入口；参数、按键和数据含义以链接的专项教程为准。

2026-10-12已按Oct 11可运行版本更新。**新建任务初始化新目录；续跑任务只启动旧目录；监控指向同一个任务目录。**

快速定位：[从BC新建空池](#rl-new) · [Ctrl+C后续跑](#rl-resume) · [通用在线启动](#rl-start) · [监控与回放](#monitor) · [外盘恢复与buffer验证](#archive-restore)。
完整资料导航见[当前训练说明与文档汇总](../docs/current_training_guide.md)；[全部项目Markdown索引](../docs/markdown_index.md)用于查找历史材料。

## 一键启动与动作菜单

在交互终端执行 [start_common_live.sh](../scripts/start_common_live.sh)：

```bash
cd /home/zhoutong/omi_folder/omi_proj
bash scripts/start_common_live.sh
```

脚本启动机器人左臂 A 接收端、D435 彩色流、Daimon 腕部 ROI 相机、双指触觉及六维 wrench，
等到 EEF、两路相机和双指触觉话题收到数据后，显示动作菜单：

1. 独立手柄操作。
2. 人工示范采集（20 秒 × 10 回合，新输出目录）。
3. 固定 BC 评估（已有 BC 目录，1 回合）。
4. 从 BC 新建在线 RL（新空池，45 秒回合）。
5. 继续已有在线 RL（恢复所选目录，不重新初始化）。
0. 关闭本次启动的设备并退出。

菜单会提示手柄路径和相关数据目录，可以回车沿用本页默认值。独立手柄默认 `/dev/input/js1`，
采集、BC、RL 默认 `/dev/input/js0`。所有进程统一使用 domain 13 和 SUBNET 发现；
可通过运行前设置 `ROS_DOMAIN_ID` 修改 domain。

Daimon 夹爪由所选动作入口连接，使用项目现有地址和标定，不需要额外夹爪进程。
手柄、采集、RL 默认启用 A 闭合 / B 张开；**此处 RL 与下文手工命令不同，默认不加 `--no-gripper`**。
现有固定 BC 入口尚未实现夹爪控制，菜单中已标注；不要为此同时另开手柄动作发布端。
如需禁用夹爪，在一键脚本后加 `--no-gripper`。

常用选项：

```bash
# 仅打印设备命令和各动作入口，不连接设备、不创建训练目录
bash scripts/start_common_live.sh --dry-run

# 首次使用或接收端代码更新后：先校验 SDK、构建，再启动
bash scripts/start_common_live.sh --build

# 直接进入指定动作；手柄编号按本机实际情况填写
bash scripts/start_common_live.sh --action gamepad --gamepad /dev/input/js1
bash scripts/start_common_live.sh --action rl-resume \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 --gamepad /dev/input/js0
```

更多参数见 `bash scripts/start_common_live.sh --help`。新 RL 的来源用 `--bc-run`，
目标用 `--run`；已有目标目录会被拒绝，续跑必须选择 `rl-resume`。

设备日志写入 `local/common_live/<本次时间戳_PID>/`，动作入口直接显示在当前终端。
可另开终端用 `tail -f <日志目录>/robot.log` 等查看设备输出，或启动下文只读看板。
反馈话题默认各等待最多 60 秒，可用 `--ready-timeout` 调整；
设备进程在动作执行期间退出会触发整套会话清理。

按一次 **Ctrl+C** 会先通知动作入口退出，等待回合审计、模型及数据保存，然后依次停止触觉、
腕部相机、D435、机器人接收端。动作自然结束后也会关闭整套设备，需要换动作时重新运行脚本。
请保留终端直到退出完成；这些进程是同一次会话的一部分，无需额外终端管理器。
启动前先停止手工启动的同类设备与动作进程；脚本锁只能阻止重复运行本脚本。
脚本会使用下文的 `motion_authorized:=true` 和工具参数连接、切换机器人模式，
执行前仍需按下文完成现场准备并核对工具参数。

## 先确定本次运行方式

| 用途 | 动作发送端 | 配套入口 |
| --- | --- | --- |
| 独立手柄操作 | `scripts/gamepad_test.py --execute` | 机器人接收端；可同时开只读看板 |
| 人工示范采集 | `scripts/collect_rl_episodes.sh --execute` | 机器人接收端、三路传感器；脚本自己读取手柄 |
| 固定 BC 评估 | `scripts/run_bc_episodes.sh --execute` | 机器人接收端、三路传感器；脚本自己读取手柄 |
| 在线 RL | `scripts/run_async_rl.sh --execute --enable-policy` | 机器人接收端、三路传感器；脚本自己读取手柄并启动 Learner |

上述四种动作发送端**一次只运行一种**。尤其运行采集、BC 或 RL 时，不要另开 `gamepad_test.py --execute`。相机、触觉、实时看板、wrench 看板和只读预警可以各占一个终端，与所选动作入口配合。开始运动前由现场操作者确认机械臂、工具、工作空间、急停及接管方式。

## 1. 准备机器人接收端

首次配置或修改接收端代码后，在一个终端校验 SDK 资源并构建；构建本身不连接机器人：

```bash
cd /home/zhoutong/omi_folder/omi_proj
python3 scripts/import_optical_module.py verify
bash scripts/robot_controller.sh build
```

在机器人终端加载 ROS 和工作区，再连接左臂 A。`connect_on_start:=true`、`motion_authorized:=true` 和 `start_mode:=3` 会连接并切换控制模式，需在现场准备完毕后执行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash

export ARM_SDK_DIR="$PWD/local/vendor/optical_module_pu/source/OpticalModule_PU/Arm_control"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

ping -c 3 192.168.14.190
ros2 launch arm_delta_cmd delta_ctrl.launch.py \
  robot_ip:=192.168.14.190 \
  arm:=A \
  connect_on_start:=true \
  motion_authorized:=true \
  manual_delta_topic:=/omi/controller_test/decision \
  delta_frame:=base \
  ctrl_rate:=200.0 \
  delta_splits:=20 \
  start_mode:=3 \
  calib_mode:=measure \
  tool_xyzabc:=[5.0,0.0,200.0,-180.0,-90.0,0.0] \
  tool_dynamic_params:=[1.3,0.0,0.0,70.0,0.0,0.0,0.0,0.0,0.0,0.0] \
  publish_root_tf:=none
```

这里将你给出的 `LOCALHOST` 发现设置改为 `SUBNET`，用于本页的网络传感器及 BC/RL 联合运行。接收端、传感器与动作进程需使用同一个 domain，并能互相发现；**修改环境变量后要重启已运行的节点**。若只做本机独立手柄测试，可在启动接收端和手柄前改用原来的设置：

```bash
export ROS_LOCALHOST_ONLY=1
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

本机独立手柄的完整流程见[机器人与手柄启动教程](robot_gamepad_startup.md)。`tool_xyzabc` 和 `tool_dynamic_params` 是当前示例工具参数，需与现场工具核对；连接时两者会一起下发到控制器。`publish_root_tf:=none` 只关闭静态 TF 发布。

## 2. 分别启动三路传感器

以下每条在**不同终端**运行；每个终端先执行本段的 `cd` 和 `export`。相机与触觉脚本的 `--transport network` 会配置网络发现；外部 RealSense 使用同一 domain：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

腕部相机，输出 128×128 ROI：

```bash
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network
```

双指触觉小矩阵及六维 wrench：

```bash
bash scripts/start_daimon_live.sh tactile --transport network --tactile-wrench
```

外部 RealSense 彩色相机，在其独立终端运行：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 launch realsense2_camera rs_launch.py
```

启动后确认实时策略实际订阅的外部 RGB 话题有图像；项目示例使用 `/camera/camera/color/image_raw`。如果本机 RealSense 的默认命名不同，参照[机器人与手柄启动教程的相机参数](robot_gamepad_startup.md#网络推理前启动传感器)显式设置 `camera_namespace`、`camera_name` 和彩色流。腕部和触觉话题、发布开关见[传感器命令速查](sensor_commands.md)。

## 3. 只读查看和触觉预警

下列命令各在独立终端运行，默认使用 domain 13；看板不会发布机械臂动作。

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

相机、触觉和 EEF 实时看板，以 10 Hz 更新图像面板：

```bash
bash scripts/view_grid_observation_live.sh --hz 10
```

双指六维 wrench 看板，曲线显示最近 60 秒，同时将收到的原始样本持续写盘：

```bash
bash scripts/view_wrench_live.sh --window 60
```

按 Start 采集基线的只读差值预警：

```bash
bash scripts/watch_bc_wrench.sh \
  --wrench-force-xy-warning 3.5 \
  --wrench-torque-warning 1.0
```

这两个阈值是**本次运行指定的试用值**，不是已标定的安全限值。脚本只打印预警，不会停止机器人、拦截策略动作或开启接收端触觉保护。它需要上面的触觉 `--tactile-wrench` 数据。详见[只读预警](tactile_warning.md)和[wrench 记录](wrench_live.md)。

## 4. 选择一种动作入口

以下入口在各自的新终端运行，先进入根目录并指定 domain：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13
```

### A. 独立手柄操作

该入口只适合单独手柄操作。先按[手柄教程](robot_gamepad_startup.md)在非执行模式核对 `/dev/input/js0` 和按键，再在新终端启动：

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

.venv/bin/python scripts/gamepad_test.py \
  --execute \
  --device /dev/input/js1 \
  --rate 10 \
  --home-button-code 314 \
  --scale 1 \
  --output-convention sdk-x-forward-z-left
```

按程序提示回车后开始发送；按住 RB 才发布非零手臂增量。该独立入口与下面三个采集/推理入口互斥。[完整按键、回位和夹爪说明](robot_gamepad_startup.md#5-终端-c启动手柄动作发布)。

### B. 人工示范采集

```bash
bash scripts/collect_rl_episodes.sh \
  --output "local/rl_episodes/demo_new_$(date +%Y%m%d_%H%M%S)" \
  --episode-seconds 20 --episodes 10 \
  --control-mode periodic --execute
```

每回合最长 20 秒、计划采集 10 回合，输出目录带本次启动时间。周期控制按 Start(315) 开始，RB 加摇杆进行人工动作；308 标记成功，307 提前结束。成功标签、有效 transition 和保存状态需以每回合审计为准，不能仅看目录是否生成。[采集操作与数据检查](rl_episode_collection.md)。

### C. 固定 BC 模型评估

```bash
bash scripts/run_bc_episodes.sh \
  --output local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --resume --control-mode periodic --episodes 1 --execute
```

从指定已有目录恢复 BC 模型，运行一个周期回合。此入口做实时网络推理和审计，**不播放训练标签，也不训练模型**。Start(315) 开始，RB 接管，308 成功，307 停止；`--resume` 继续使用该目录而不覆盖已有回合。运行前核对目录中的权重和版本。[BC 评估及标签回放的区别](bc_replay_testing.md)。

### D. 异步在线 RL：新建与续跑

#### D1. 为什么没有 `--resume`？

**`run_async_rl.sh --run 已有任务目录` 本身就是自动恢复入口，不需要、也没有 `--resume` 参数。**
它读取指定目录的 `config.json`、`async_session.json`，Actor加载 `actor.pt`，Learner存在 `learner.pt`
时调用 `SAC.restore` 恢复完整状态，再打开既有replay索引。正常Ctrl+C后不重新初始化、不清空已有数据。

| 你的目的 | 应该执行什么 | 模型和数据如何处理 |
| --- | --- | --- |
| 从原BC开始新采一批数据 | **D2，然后D4** | 新目录；继承BC Actor/归一化；新Critic/优化器/计数；Demo/RL均空 |
| 继续一个已Ctrl+C的在线任务 | **D3，然后D4** | 原目录；恢复Actor、Learner、优化器、累计步数和已有数据 |
| 从外盘完整归档恢复到新目录 | **F恢复，再D4** | 新目录中保留归档的完整RL状态和数据；不是重新从BC开始 |
| 用任意RL checkpoint另起新空池 | **当前没有通用初始化入口** | 不能把RL目录直接填进 `--bc-run`，也不要只替换 `actor.pt` |
| 固定BC评估、不训练 | 上面的C入口 | `run_bc_episodes.sh --resume` 是另一套CLI，与在线RL不同 |
| 离线验证Learner | G入口 | 不采集、不启动机器人；会更新指定副本中的权重 |

`prepare_bc_rl.sh`目前只接受来源目录中 `training_method=behavior_cloning` 的 `actor.pt`。
任意RL checkpoint→新目录空池仍是待补齐能力；不能拿“完整归档恢复”冒充“只继承RL权重”。
`run_async_rl.sh --initialize-from`也不是这个通用入口，它面向已停止的离线seed副本，且会复制其replay。

**D2和D3二选一，不要依次全执行，否则 `$run_dir` 会被改到另一个任务。**
原任务需先正常退出；新建/续跑时沿用接收端和传感器，只运行一套动作发送入口。

<a id="rl-new"></a>
#### D2. 从BC初始化新目录：只用新采集的数据

在训练终端执行一次。`run_dir`由时间戳生成，目标目录必须尚不存在：

```bash
cd /home/zhoutong/omi_folder/omi_proj

run_dir="local/rl_training/new_run_$(date +%Y%m%d_%H%M%S)"
echo "本次任务目录：$run_dir"

bash scripts/prepare_bc_rl.sh \
  --bc-run local/bc_episodes/demo_new_20261007_213643_eval_01 \
  --run "$run_dir" \
  --weights-only \
  --episode-seconds 45 \
  --replay-backend cached \
  --cache-target-gib 16 --cache-limit-gib 20 \
  --critic-warmup-updates 1000
```

初始化成功后，**同一个终端直接执行D4，不执行D3**。

- `--bc-run`是来源目录，不是单个`.pt`路径；脚本读取其 `actor.pt` 和配置。
- `--run`是新任务目录。不会覆盖旧任务，也不会删除原BC。
- `--weights-only`表示不导入旧Demo或旧RL数据，不能同时传 `--recorded-source`。
  **仅省略recorded-source、却不加weights-only，仍会导入来源BC的旧Demo。**
- `--episode-seconds 45`设置新任务时限，单位秒；想用30秒就改为30。仅在新建weights-only任务时设置，
  不要只修改已有 `config.json`，否则可能与checkpoint、session和replay契约冲突。
- 初始RL版本0表示更新计数从0开始；Actor参数已经完整预加载BC12045，并非随机Actor。
- 新池需要本批人工接管数据。D4设定Demo至少100条、RL至少100条；人工有效transition同时属于两池，
  需结束回合并完成入池后才可采样。只有策略数据时，Learner会等待Demo。

需要保留旧Demo或额外历史采集的另一种配置见[缓存教程](cached_replay.md)，不要与本节的“只用新数据”混用。

<a id="rl-resume"></a>
#### D3. 继续已Ctrl+C退出的任务：保留模型、进度和数据

在训练终端选择**原目录**，不再调用prepare：

```bash
cd /home/zhoutong/omi_folder/omi_proj
run_dir="local/rl_training/bc12045_newdata_30s_20261011_01"
echo "继续任务：$run_dir"
```

然后在同一终端执行D4。这个目录在Oct 11停止时最终checkpoint为16677，两个buffer的磁盘数据也保留。
虽然目录名含 `30s`，实际会话时限已改为 **45秒**，续跑沿用保存配置。
本机原目录仍保留；恢复这批checkpoint与数据本身不需要先连接外盘或解包归档。

恢复的内容包括Actor/Critic/target、温度、优化器、累计更新数、保存的随机状态、replay索引和原始数据。
内存buffer会重新填充，不保证恢复成退出瞬间相同的驻留成员或随机抽样次序。
未完成登记的已保存回合由导入流程补入；本次最后449条属于这种情况。

<a id="rl-start"></a>
#### D4. 通用启动命令：新建和续跑都用这一段

**前提：已通过D2或D3设置好 `$run_dir`，并确认准备命令成功或旧任务完整存在。**
新终端不继承另一个终端中的变量，需要重新赋值。

```bash
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run "$run_dir" \
  --actor-device cuda --learner-device cuda \
  --batch-size 64 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 \
  --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy
```

如果只想复制一整块指令续跑当前Oct 11任务，用下面这一块即可；**与上面二选一，不要同时执行**：

```bash
cd /home/zhoutong/omi_folder/omi_proj
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

bash scripts/run_async_rl.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --actor-device cuda --learner-device cuda \
  --batch-size 64 --publish-every 50 \
  --reload-every-episodes 10 \
  --min-online 100 --min-demo 100 \
  --max-updates-per-transition 1 \
  --arbitration-mode after-inference \
  --exploration-noise-std 0.05 \
  --exploration-noise-clip 0.15 \
  --no-gripper --execute --enable-policy \
  --tag-follow-calibration /home/zhoutong/omi_folder/omi_proj/ros2/marker_detect/handeye_result.json
```

这正是“resume”：同一路径下已有checkpoint和数据，程序自动恢复，而非重新训练一个随机模型。
`POLICY_LOADED: version=...`显示Actor实际加载版本；未进一步训练时，该归档基线为16677，以启动日志为准。
Start开始新回合，RB＋摇杆接管，308成功，307提前结束；`--no-gripper`仅禁用A/B夹爪控制，不主动闭合夹爪。

这条命令同时启用[训练内置 AprilTag 跟随](async_rl.md#tag-follow)：LB+305 保存默认相对位姿，LB+304 开始/停止；跟随期间暂停策略与回合计时，跟随动作不入训练回放。不要另开独立跟随脚本。默认手柄为 js0，若设备编号改变，在命令中追加 `--gamepad /dev/input/jsN`，用[设备列表](marker_detect.md#tag-follow)确认 Xbox 的实际编号。当前增益0.08、每轴每周期上限0.5 mm/0.2°，平移/旋转各自进入死区后归零，均保持时显示 `HOLDING`。

#### D5. 哪些参数随checkpoint恢复，哪些每次写在命令里？

| 设置 | 来源／行为 |
| --- | --- |
| 模型参数、优化器、累计步数、gamma、冻结方式、预热设置 | `learner.pt`恢复；不是改源码默认值就会改变旧任务 |
| 回合45秒、观测/动作契约 | 保存的config及匹配的模型/session/replay契约 |
| batch64、发布间隔50、换权重间隔10 | 本次启动命令明确指定 |
| 探索std0.05、clip0.15 | 每次启动明确指定；不传std默认关闭探索 |
| 更新预算1 | 每次传入；累计Critic上限=1000预热＋已登记online条数×1，用完等待新增数据 |
| 16/20 GiB缓存预算 | 已有replay manifest；16是合计驻留目标，20是受管管线上限，不是总RSS/显存上限 |

Actor等待Start时Learner可以继续学习到预算上限；Ctrl+C关闭在线入口会同时关闭Actor/Learner。
Learner每50次Critic更新发布权重；Actor每新增10个有效回合在边界检查新版本，回合中途不换。
重启时立即加载最新权重并重置本次检查基点，不需要先等10个回合。

<a id="monitor"></a>
### E. 可视化：指向同一个任务目录

监控是独立只读进程，不启动训练。**不需要在浏览器里选文件夹，命令的 `--run` 就是数据目录。**
当前本机Oct 11会话：

```bash
cd /home/zhoutong/omi_folder/omi_proj

bash scripts/view_training_monitor.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --port 8771
```

打开 **http://127.0.0.1:8771/**。如果是D2的新任务，将 `--run` 换成D2打印的新目录。
新终端不会继承 `$run_dir`；在监控终端重新赋值或直接写实际路径，不要把变量为空的命令直接运行。
已经能正常打开同一任务的网页时，刷新即可，不需要重复启动。切换任务可关闭旧监控再运行，
或换用 `--port 8772` 并打开8772网址；同一端口不能同时运行两套服务。

页面重点看：

- **权重同步 → Actor已加载**：实际执行策略版本；“最近发布确认”只表示可供加载，不代表Actor已采用。
- **Demo / RL Buffer**：内存可采样与磁盘登记分别显示；人工交集共享，两个数量不能直接相加。
- **未成功合计**：包含timeout、人工提前结束、异常中止等；“异常中止”不包含普通timeout。
- **进行中 / 暂存**：正在采集或保存时，待audit落盘后再归入结束结果。点击卡片可筛选回合。
- 训练已关闭时网页保留历史快照，不代表训练仍在进行；关闭网页也不会停止训练。

只看相机/触觉及逐帧回放，可另开这个入口（与训练状态网页不同）：

```bash
bash scripts/view_rl_episodes.sh \
  --run local/rl_training/bc12045_newdata_30s_20261011_01 \
  --port 8772
```

打开 http://127.0.0.1:8772/ 。上述8772仅为可选空闲端口，若已用于另一个监控，需换端口。
详细说明见[训练监控](training_monitor.md)与[回合回放](rl_episode_visual_review.md)。

<a id="archive-restore"></a>
### F. 外盘归档恢复与buffer重建

Oct 11归档位于 `/media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data/`。
外盘已在此前操作中安全退出；需要读取归档时重新连接并挂载到实际路径。本机原会话仍保留，
**仅续跑D3不必先执行本节**。

| 归档内容 | 相对归档根目录的路径 |
| --- | --- |
| 完整会话：原始数据、索引、日志及模型 | `run.tar` |
| 最终策略 / 完整Learner状态 | `checkpoints/actor.pt` / `checkpoints/learner.pt`，均16677 |
| 原始BC12045 | `initial_bc/actor.pt`，配套config/recipe同目录 |
| 标准库恢复工具与教程 | `archive_tool.py`、`README.md`、`RESTORE_VALIDATION.md` |
| 代码与完整性信息 | `source.tar`、`manifest.json`、逐文件SHA清单 |

外盘挂载后，在项目根目录执行：

```bash
bash scripts/training_archive.sh verify \
  --archive /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data

bash scripts/training_archive.sh restore \
  --archive /media/zhoutong/zt-think-d1/legion_data/date_related/oct_11_data \
  --dest local/rl_training/oct11_restored_01
```

目标必须是尚不存在的本机目录，恢复成功后模型和数据保持归档内容；不要直接在exFAT归档目录上续训。
只验证buffer恢复、不训练、不启动机器人：

```bash
bash scripts/training_archive.sh probe-buffer \
  --run local/rl_training/oct11_restored_01 \
  --cache-target-gib 1 --cache-limit-gib 2 \
  --batch-size 64
```

1/2 GiB只用于这次临时验证，不覆盖正式16/20 GiB预算；正式Learner启动会自动从SQLite和原始帧重建RAM缓存。
恢复副本续训时，在训练终端设置 `run_dir="local/rl_training/oct11_restored_01"` 再执行D4；
其网页也必须指向这个恢复目录。
这是**完整RL状态和数据的恢复**，不等于“只用任意RL checkpoint、新建空buffer”。
校验、代码恢复、重新归档及环境要求见[外盘复现教程](oct11_archive_restore.md)。

### G. 只跑Learner的离线验证（不是真机采集入口）

以下只针对F已恢复的副本，追加20次更新后退出，不启动Actor/机器人，但会更新这个副本中的模型：

```bash
local/cuda-env/bin/python -m omi_hil_rl.hil.learner \
  --run local/rl_training/oct11_restored_01 \
  --config local/rl_training/oct11_restored_01/config.json \
  --device cuda --batch-size 64 \
  --min-online 100 --min-demo 100 \
  --publish-every 50 --updates 20 \
  --max-updates-per-transition 1
```

`--updates 20`是追加20次，不是把累计进度改成20。若更新预算已耗尽则等待新增数据。
此前的 `run_cached_offline_experiment.py` 是读取历史数据做留出对照的另一种离线实验；
日常在线采集使用D4，不使用该实验脚本。见[离线对照记录](../docs/agent/training/chronicles/2026-10-11-critic-diagnostics.md)。

## 停止与记录

先停止当前动作入口，等待其回合审计与写盘完成，再按需停止看板和传感器，最后停止接收端。看板的关闭不会停止其他采集进程。BC/RL 日志中的“本地保存完成”不等于 Learner 已导入；RL 以运行目录的 `status.json`、`async_state.json`、`learner.log` 和 `imported.json` 核查。若实时观测、接收回执或运动异常，使用现场接管/停止流程，保留日志供复查。

在在线训练终端按一次Ctrl+C，等待保存结束、`CLOSED`及终端提示符恢复后再关终端。正常退出保存最终checkpoint；
回合中退出的审计/入池状态以 `audit.json` 为准，不能把退出当作成功标记。
接收端、传感器和网页是独立进程，不会随Actor/Learner一起退出。
