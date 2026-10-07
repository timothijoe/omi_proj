# RViz双臂3D回放＋视觉触觉看板

若检查当前record001的Stand机器人姿态，优先看[关节方向修正版](corrected_stand_review.md)
（domain94）。本文保留旧record010及旧模型record001入口；它们没有被覆盖。
各版用途与domain见[版本对照表](../docs/agent/hardware/evolution/robot-3d-replay.md#入口选择与当前结论)。

## 启动

项目根目录直接执行，无需每次export路径：

```bash
bash scripts/view_observation_robot_3d_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001
```

参数为 `BAG [RATE=1.0] [--no-rviz]`。默认localhost domain96，Ctrl+C关闭全部子进程。
旧 `view_observation_bag.sh`、文字版 `view_observation_robot_bag.sh` 继续可用，互不替换。
本机依赖位置自动读取 `local/robot_state/viewer.env`，换机配置见[文字版教程](robot_state_dashboard.md)。

RViz中央是可旋转/缩放的双臂3D模型，Image面板仍显示相机、触觉与机器人文字状态。
模型旁显示回放/暂停/缺失状态与未标定提示。不存在的TCP不补造；图像窗口大小可拖动调整。

## 模型来源和限制

- 读取项目本地 `local/assets/robot_assets/mujoco/right_chopping_scene.xml`，生成仅包含
  robot_base和左右14个关节链的可视化URDF。网格来自相邻的 `local/assets/MarvinCCS/`。
- 排除源场景的桌面道具、灵巧手和刀具；它们不代表record010中的现场触觉夹爪。
  **本版显示到双臂末端连杆，不含已校准的触觉夹爪、手指开合或工具TCP。**
- 不显示头部/躯干运动。根基座沿用本地模型的固定姿态，不代表现场外参。
- 按Marvin消息定义前7轴L、后7轴R映射left/right_joint1..7，显示时假设反馈角度单位rad。
  该假设与现有数据量级相符，但现场方向/零点/单位仍需采集方确认。
- 数值FK与原MuJoCo模型一致不代表模型和现场设备一致；不能用本显示做安全限位、碰撞判断或TCP标定。
  模型限位外反馈不裁剪，状态报告列出对应关节，便于发现模型/单位不匹配。
- 可用 `OMI_REPLAY_ARM_SCENE`指定同结构的源场景；转换器仅支持当前显式四元数/位置、
  原点处hinge关节和mesh几何，非通用MJCF转换工具。不支持的结构会拒绝，不能默默猜测转换。

## 回放与安全边界

离线解码机器人时间线，沿用文字版看板参考header，从历史反馈中取不晚于参考的最近样本。
**不回放关节命令/夹爪控制，不启动硬件驱动或控制器。** 原播放器仍只播放图像白名单。

新增可视化流全部在 `/omi/replay_3d/` 下：

| Topic | 用途 |
| --- | --- |
| joint_states | 14轴记录角度，供robot_state_publisher绘图，不是控制命令 |
| robot_description | 生成URDF，transient-local发布 |
| tf、tf_static | RViz专用变换，链接名带omi_replay_前缀 |
| status | 参考/源时间、滞后、状态、限位提示和假设 |
| notice | 3D文字提示 |

RViz的TF订阅被重映射到以上独立TF话题；不发布全局 `/joint_states` 或控制topic。
关节消息/TF用当前显示时钟，避免bag循环时间倒退导致TF拒绝；历史源时间另存status。
这不是原始录包时钟TF，不应作为训练时间戳输入或真实在线机器人TF。

反馈超过0.25秒、参考时间超过0.5秒不推进会标STALE/PAUSED；旧姿态可保持显示但不能看作实时有效值。
尚无有效样本时不伪造零关节角，缺失动态TF属于等待状态。该回放的多模态对齐仍是近似参考，非硬同步。

## 依赖与本地生成文件

除文字版看板依赖之外，还需要目标机安装 `ros-jazzy-robot-state-publisher`、RViz及标准消息包。
本轮实现/验证仅针对Jazzy；不宣称Humble新入口已验证。
额外拷贝模型时保留 `robot_assets` 与 `MarvinCCS` 相邻布局；不需要拷贝外部参考工程。
厂商模型不新增提交至Git。

生成的URDF、publisher参数与来源摘要位于 `local/robot_state/models/<hash>/`，
网格通过绝对file URI引用本机资源，换机器应重新生成；URDF哈希不代替网格完整性校验。
机器人时间线缓存和临时解压空间要求沿用文字版。

## 验证入口

```bash
# 已source Jazzy，使用具备ROS/NumPy/Pillow的Python环境；不连接硬件。
local/venvs/daimon312/bin/python scripts/check_robot_3d_replay.py /PATH/TO/BAG
# --gui会打开RViz，抓取一次桌面截图用于人工检查，测试结束关闭所启动进程。
```

默认隔离domain98、2倍速、42秒，检查关节变化、TF/模型描述、图像、循环和无控制topic。
报告位于 `local/robot_state/3d_check/`。单元测试在 `tests/test_robot_replay_3d.py`，
资产未恢复时模型FK对照测试会跳过，不应把跳过说成现场通过。

## 新录包原生数值场入口（2026-10-02）

旧入口保持原样。对于包含 `/tj/dm_sensor/{a,b}_{deformation,shear}` 和
`/tj/info/eef_left` 的新包，使用独立入口，可直接读取 ZIP：
当前本机代表命令使用 bag_004；本节后文 record001 的数值和缺少腕部图像的结论仍只属于原 record001 实验。

```bash
bash scripts/view_recorded_observation_3d.sh --help
bash scripts/view_recorded_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip
# 第二个参数为倍速，第三个可选 --no-rviz。
```

显示相机原图及黄色ROI、既有 observation 配置的128×128相机裁剪图、
两侧触觉原图与128×128预览、录制的 deformation/shear、depth、六维力、末端位姿。
触觉128预览不是已确定的策略输入规格。数值场直接读取，不调用SDK重建。
箭头固定 step=16、20像素/数值单位、deadband=0.01、24像素截断；红色只表示显示截断。
该新包数值范围较小，因此显示增益不同于旧重建看板，不可直接比较两版箭头长度。
深度固定色阶0..0.3 SDK原始单位，超出范围显示饱和，不宣称毫米/压力。

3D模型来自现有14轴模型，关节按左7轴、右7轴及弧度解释，尚未实机标定。
红/绿/蓝三轴表示录制末端姿态的X/Y/Z，末端暂按用户约定解释为夹爪抓取中心。
**只为可视化暂假定录包base_link对应模型robot_base；两者的实际对应关系未验证。**
本次实测模型末端与记录抓取中心不重合，不能把该显示当成已标定TCP；不人为补偿偏移。
其他frame_id不绘制末端三轴。没有夹爪网格，不凭单个末端位姿猜测整臂关节角。

首次离线解压、逐条读取并缓存10 Hz看板PNG及关节/末端状态，之后直接循环播放。
缓存位于 `local/recorded_review/<signature>/`，源ZIP不变；准备时需约2GB临时空间，
此13.55秒示例生成136个显示帧。只保留最新输入，避免把全部原始数值场存入内存。
按bag接收顺序取最近已到达值，并显示各自header相对显示参考时刻的年龄；
超过250ms标STALE，尚未到达标WAITING。这不是同一SDK帧验证或训练数据同步导出器。
拒绝倒退的源时间、晚于接收时间的源时间、无效数值，避免隐式跨时钟拼接。
新入口循环开头尚无关节反馈时显示零角占位，面板明确WAITING，不沿用上一轮末尾姿态。

独立localhost domain97；只发布 `/omi/recorded/{dashboard,eef,status}` 和
`/omi/replay_3d/` 下的显示用关节、模型、TF，不播放原包控制topic。
关闭RViz或Ctrl+C清理本入口子进程。并发打开另一份时可用 `OMI_RECORDED_DOMAIN_ID` 分域。
依赖仍使用本地 viewer.env 的 Marvin 消息overlay、现有模型资产，以及Jazzy、
robot_state_publisher、NumPy、Pillow、SciPy、PyYAML、zstd；不需要连接触觉SDK或机器人。
Humble尚未验证，脚本目前明确source Jazzy。

实包GUI播放已验证，验收数字见[开发记录](../docs/agent/hardware/chronicles/2026-10-02-native-record-review.md)。
若看到末端三轴远离模型，不要直接加平移让其重合：先取得录包生产者的base_link定义、
实际机器人模型与工具变换。这里domain97旧模型的约0.93米位置差仍保留；
新domain94方向修正版已改善高度对应，但工具偏移/基座定义尚未标定，不能用于控制。
270×360触觉原图用于检查源数据；128×128触觉图只是直接缩放预览，会改变原图宽高比。

当前布局：右上角为A/B整图缩至128×128再双线性插值放大的预览，显示占用范围与原图相同；
右下角为A/B原始raw。这里没有去畸变或新ROI裁剪，也不强制512×512显示。
注意：这不是腕部相机画面。用户期望右上角显示腕部相机原图与clip，该功能仍待修改；
当前新record001包缺少腕部图像，换命令或重启不能补出它，需要采集方补录。
放大只是显示插值，不增加源信息。缓存版本已更新，首次运行会生成新版布局缓存，
保留旧缓存不覆盖；之后播放读取缓存，不在播放时运行SDK或重新绘制数值场。
