# 实时相机、触觉与末端位姿 RViz 看板

在项目根目录执行：

```bash
bash scripts/view_grid_observation_live.sh
```

默认订阅网络ROS **domain13**，打开RViz；不需要rosbag路径。
该脚本不启动传感器、机器人驱动或策略，不发送运动命令，不播放bag。
原`view_grid_observation_3d.sh BAG`继续负责离线回放。

界面保留外部原图＋128 ROI、腕部128 ROI、双指deformation/shear箭头与depth热力图。
默认沿用原来的方向修正版 Stand 模型；三维区分别显示模型 L7 原点与 ROS 末端坐标轴。
显示约定仍为 base_link 与模型根重合，尚不是基座/TCP标定结论。
每路topic有接收Hz、最近接收年龄、源header年龄、发布者数量和必需/可选标记。
默认刷新2Hz；这是看板刷新率，不是传感器或policy频率。

```bash
bash scripts/view_grid_observation_live.sh --domain 13 --hz 5
bash scripts/view_grid_observation_live.sh --model-mode none --fixed-frame base_link
# 不打开GUI，12秒检查后退出
bash scripts/view_grid_observation_live.sh --no-rviz --duration 12
```

关闭RViz或启动终端Ctrl+C结束本次看板及其子进程，不停止已有采集进程。
同一domain只允许一个本脚本实例。使用的ROS发行版来自ROS_DISTRO，默认Jazzy；本机只验证Jazzy。

## 状态解释

- LIVE：数据形状合法且未超过新鲜度阈值。第三视角外部RGB只按本机接收年龄判断；其他输入仍同时检查本机接收年龄和源header年龄。
- NO_PUBLISHER：本机ROS图尚未发现发布者，不代表设备物理不存在。
- WAITING：发现发布者但尚未收到可解码数据；检查域、网络、消息定义与QoS。
- STALE：距上次有效接收超过阈值；图像/场面板不继续显示旧图。
- OLD_HEADER / CLOCK_AHEAD：非外部RGB输入的源header太旧或超前超过100ms。外部RGB的header年龄仍显示在表格与status.json中，仅作时钟和传输诊断，不控制此看板的显示。
- BAD_DATA：形状、非有限值、时间戳或四元数等解码检查失败；详细原因在status JSON。
- FRAME_CHECK：末端frame不是训练约定base_link，不能仅改名字绕过。

末端阈值50ms、其余250ms；外部RGB以本机单调接收时钟判断250ms内是否持续到达。
外部RGB显示为LIVE只说明最近收到图像，不证明曝光到接收的端到端延迟小于250ms。
本次规则只适用于只读看板；policy的源header检查和输入契约没有改变。
各传感器独立取最新帧，不保证同时采样、同SDK帧或完整policy输入一致性。
统计Hz为最近3秒收到消息的间隔估计，消息计数包含随后被判为异常的消息。
非外部RGB的旧header等异常图像不显示，但底部保留状态及最后末端数值并标记状态。

必需检查项按双相机无关节方案：外部RGB、腕部ROI、双指三场、左臂EEF。
关节、wrench、raw仅供检查，为可选项；这不是checkpoint自动识别器。
若将来使用不同输入配置，应调整监测契约。

## 三维模型

默认 `--model-mode corrected` 使用：
`local/models/omi_marvin_stand_axis_corrected_v1/urdf/omi_marvin_stand_axis_corrected_v1.urdf`。
沿用原回放的 `/tj/info/joint_feedback.positions` 14维顺序（左7、右7）、弧度约定；
URDF已修正轴方向，不再额外翻转关节符号。不自动猜测或混用 `/tj/joint_states` 的单位。
无关节策略输入仍不需要关节；三维机器人姿态显示需要关节反馈。

`/tj/info/eef_left` 仅在 frame 为 `base_link` 时按原先基座重合假设叠加。
L7使用6cm坐标轴，ROS EEF使用12cm坐标轴，各有标签；不添加猜测的TCP偏移。
超过250ms未收到新数据就停止更新相应三维显示；关节TF可能保留最后姿态，
醒目标记 `NO FRESH JOINTS: model absent or FROZEN`，不补零伪造实时姿态。
三维排查允许显示刚收到但header时间异常的数据，并保留其状态标签；
看板的严格LIVE检查与策略契约没有放宽。EEF frame不符则不叠加。

```bash
# 使用现场原有 /robot_description 和 TF（需要本机具备对应网格）
bash scripts/view_grid_observation_live.sh --model-mode existing
# 仅显示现场 EEF，无机器人模型
bash scripts/view_grid_observation_live.sh --model-mode none
```

`--robot-model` 保留为 existing 模式的兼容选项。
修正版模型使用 `/omi/live_grid/model/` 下独立的 robot_description、joint_states、tf、tf_static，
RViz只读取这套显示TF，不向现场 `/tf`、`/tf_static`、`/joint_states` 注入变换或关节。

## 输出与依赖

输出 `/omi/live_grid/dashboard`（rgb8 Image）、`/omi/live_grid/status`（JSON String）、
`/omi/live_grid/model_markers`（三维标记）及上述独立模型话题，
另有ROS节点自带日志/参数事件。RViz工具仅保留Interact/MoveCamera，不提供导航目标发布工具。

每次启动创建`local/grid_live_review/session-*`，保存live.rviz、最新dashboard.png及status.json。
`--output NEW_DIRECTORY`可固定新目录；拒绝覆盖已有目录。
网络DDS配置仅用于本看板和RViz子进程：64MiB SHM、大图上限8MiB及网络UDP发现，
不修改其他采集进程或系统网络配置。看板发布大图有额外负载，需要时保持默认2Hz。

依赖沿用录包看板：ROS Jazzy、RViz、NumPy/Pillow及可选marvin_msgs。
缺marvin_msgs时跳过可选关节订阅；即使其余topic缺失仍能显示状态。
现场证据和限制见[纪传体](../docs/agent/hardware/evolution/grid-live-review.md)。

## 现场 Jointfeedback 定义（2026-10-04 修正）

现场接口为 Header + float64[14] positions/velocities/efforts；与历史bag的
arm_positions/arm_velocities/arm_efforts及躯干、头部字段版本不同。
类型名字相同不表示字段布局相同；旧定义对现场356字节样本反序列化失败。
现场接口源码在 `ros2/live_feedback_interfaces/marvin_msgs`，单独编译：

```bash
source /opt/ros/jazzy/setup.bash
colcon --log-base local/live_feedback_ws/log build \
  --base-paths ros2/live_feedback_interfaces \
  --build-base local/live_feedback_ws/build \
  --install-base local/live_feedback_ws/install \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3
```

实时脚本默认加载这个工作区的local_setup.bash；可用 `OMI_LIVE_MARVIN_MSGS_SETUP`
指定匹配现场的接口包。原录包工具及 `OMI_MARVIN_MSGS_SETUP` 保持原定义。
此最小实时包只提供Jointfeedback，不是完整机器人控制接口包。
验证5秒收到250条，约50Hz。该时刻positions前7为零、后7非零；
显示保留接口注释的左7/右7顺序，但实际左右臂对应与零值是否代表有效反馈仍待核对。

三维对比增加青色L7球、品红色EEF球和黄色连线，实时显示两者距离、坐标轴相对转角及消息时间差。
数值使用独立最新样本、原基座重合假设；L7不是TCP，因此连线距离不是已标定的TCP误差。

## 三维刷新与图像看板分离

`--model-hz 30`为独立三维进程的默认更新率，RViz渲染上限30Hz；`--hz 2`仅控制图像看板。
原先10Hz大图绘制和PNG保存堵塞同进程订阅，实测EEF源约49Hz、显示更新约6.7Hz。
现拆分`omi_live_model_monitor`仅订阅关节/EEF并发布三维标记与显示关节，
不受看板渲染/落盘直接阻塞。`model_status.json`保存独立三维进程的接收统计，
与`status.json`的图像看板统计区分。建议启动：

```bash
bash scripts/view_grid_observation_live.sh --hz 2 --model-hz 30
```

此修改不应用任何EEF平移补偿，原始坐标与模型假设不变。

## 实时 EEF 显示坐标（2026-10-07）

corrected 模型模式直接显示 `/tj/info/eef_left` 的原始 `base_link` 位姿，不再叠加
2026-10-04 使用的临时平移 `[-0.062159, -0.171229, +0.000024] m`。
品红球、坐标轴及 L7 连线均使用原始 EEF；`--eef-offset-base-m` 参数已移除。
发布端左臂 A 的固定安装平移改为 `(0, 0.0260, 1.121) m`，因此新 EEF
比旧安装变换的 Y 坐标减少 174.5 mm。历史录包内容不变；`model_status.json`
的 `display.eef` 记录当前显示所用的原始位姿。

黄色线仍显示 L7 到 EEF 的距离；相对旧回放包局部关系的残差仅供对照，
不能视为多姿态 TCP 标定结果。
