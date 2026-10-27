> 历史资料：原路径 `tutorials/README.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../current.md)；本页保留原过程与证据。

# 操作教程

- [实时观测V2：独立原图、触觉面板与延迟诊断](../../../../tutorials/grid_live_review_v2.md)，原V1入口保留。

- [SpacePilot BC6148在线RL：显式setting、旧参数对照、触觉解冻、30秒与累计300回合](../../../../tutorials/spacepilot_bc6148_online_rl.md)

- [SpacePilot 初版测试：确认键位、只读预览和完整单回合采集指令](../../teleoperation/tutorials/spacepilot_first_trial.md)

- [SpacePilot用于BC/RL采集及在线接管：按键配置、预览和输入选择](../../../../tutorials/spacepilot_hil.md)

- [SpacePilot 控制机械臂：预览、发送与独立平移/旋转 scale](../../../../tutorials/spacepilot_control.md)

- [SpacePilot 六自由度物体操控](../../../../tutorials/spacepilot_pose.md)：驱动检查、前 +X / 左 +Y / 上 +Z、实体按键、平移/旋转锁定与导出。

- [当前训练操作总览与文档汇总](../../../current_training_guide.md)：先分清新建空池、旧任务续跑和归档恢复。
- [Ubuntu 22.04 在线 RL 与人工回合采集依赖](../../../../tutorials/ubuntu2204_online_rl_dependencies.md)：现有传感器和机器人之外的 Python、ROS 与 CUDA 环境检查。
- [新建 / 自动续跑 / 监控的可复制命令](../../../../tutorials/common_live_commands.md#rl-new)：在线RL没有resume参数，按任务目录自动恢复。
- [Oct 11归档、checkpoint恢复、buffer重建与续训](../../replay/tutorials/oct11_archive_restore.md)。
- [全部项目Markdown索引](../../../markdown_index.md)。

- [AprilTag：位姿记录、多姿态手眼标定与手柄跟随](../../../../tutorials/marker_detect.md)；[独立窗口启动及排错](../../../../tutorials/marker_detect.md#tag-follow) · [首次标定](../../../../tutorials/marker_detect.md#tag-handeye) · [异步 RL 内置跟随](../../../../tutorials/async_rl.md#tag-follow)。

- [Demo/RL共享内存缓存：16/20 GiB预算、自动读取录制数据与启动](../../../../tutorials/cached_replay.md)

- [BC12045 预加载与异步 RL 首次试跑：新会话、3 回合命令、默认仲裁与监控](../../online-rl/tutorials/bc12045_async_rl_trial.md)

- [Actor/Learner 统一训练监控：传感器、仲裁、数据链、权重与逐帧审阅](../../../../tutorials/training_monitor.md)

- [local 大数据外置：原路径兼容、挂载检查与旧会话恢复](../../../../tutorials/local_data_storage.md)

- [真机 RL 回合逐帧可视化：两路相机、10 帧历史、触觉与训练片段状态](../../../../tutorials/rl_episode_visual_review.md)

- [真机常用启动指令汇总：机器人、三路传感器、看板、手柄、示范、BC 与 RL](../../../../tutorials/common_live_commands.md)

- [BC模型与成功label回放测试：295/3295/11795模型切换、按键及记录边界](../../bc/tutorials/bc_replay_testing.md)

- [异步真机RL：Actor/Learner并行，每10个完整回合刷新策略](../../../../tutorials/async_rl.md)；[Start保留十帧输入与重启生效](../../../../tutorials/async_rl.md#2026-10-09start-保留十帧输入)

- [按回合交替RL：采集后训练、重载策略、RB复位与下一回合](../../../../tutorials/alternating_rl.md)

- [RViz 操作教程：现场传感器、手柄、实时看板与历代三包回放的一行式命令](../../../../tutorials/rviz_representative_bags.md)

- [真机RL人工回合：按钮成功、超时停止、手柄复位和连续采集](../../../../tutorials/rl_episode_collection.md)

- [当前无wrench模型：推理、RB接管、单按314回home、Ctrl+C观测保存](../../../../tutorials/no_wrench_policy_record.md)

- [独立传感器采集、腕部可靠录制与时间审计](../../../../tutorials/sensor_decoupling.md)

- [新wrench BC模型真机入口：默认预览、RB手柄优先、单按314回home](../../../../tutorials/wrench_policy_gamepad.md)

- [本次日期bag转训练集：双指六维力/力矩BC训练](../../../../tutorials/passive_bag_bc_wrench.md)

- [独立手柄录包、四包检查、真实指令预览与左右键切帧](../../../../tutorials/demo_bag_dataset.md)

- [集成手柄 Demo 采集、发送指令标签与 BC](../../../../tutorials/demo_collection_bc.md)

- [六维真机HIL环境、无夹爪SAC与Actor/Learner](../../../../tutorials/hil_actor_learner.md)

- [USB 插入触觉保护：峰值锁定和负 X 撤退](../../../../tutorials/tactile_guard.md)
- [只读触觉预警：读取原始示数，超限打印日志](../../../../tutorials/tactile_warning.md)
- [双指六维力/力矩：实时查看和完整历史记录](../../../../tutorials/wrench_live.md)

- [机器人控制接收端：速度保持、参数、重启与离线预览](../../../../tutorials/robot_controller.md)

- [无关节模型实时 ROS 影子推理](../../../../tutorials/stack_shadow.md)

- [实时相机、触觉与末端位姿RViz看板](../../../../tutorials/grid_live_review.md)


- [不使用关节反馈的GPU训练](../../policy/tutorials/nojoint_stack_training.md)


- [六关键点候选与人工审核工具](../../../../tutorials/six_keypoint_review.md)

- [当前帧独立＋过去9帧通道拼接训练](../../policy/tutorials/current_stack_history.md)

- [冻结ResNet-10历史策略训练与对照](../../policy/tutorials/resnet10_history.md)

- [历史 policy 在线推理与 wrench 开关](../../../../tutorials/eef_history_online.md)

- [oct3正式录包检查、学习格式转换与训练](../../bc/tutorials/oct3_formal_dataset.md)

传感器常用操作优先看三个互相索引的教程：

- [腕部＋触觉常用命令速查](../../../../tutorials/sensor_commands.md)
- [腕部相机专项](../../../../tutorials/wrist_camera.md)
- [触觉专项：小矩阵、raw/wrench开关与录包](../../../../tutorials/tactile_grid_transport.md)

默认参数、topic和常用命令变更时，三份文件共同维护。

- [24×16触觉＋腕部ROI＋3D机器人通用回放](../../../../tutorials/grid_bag_review.md)：用于新的`/omi/tactile_grid24x16/...`录包。

- [末端动作 rosbag、Float64MultiArray 与模拟控制端联调](../../policy/tutorials/eef_action_bag.md)

- [戴蒙触觉与腕部相机独立实时启动、RViz及时延检查](../../../../tutorials/daimon_live.md)

- [bag_004末端动作空间、BC与类型化影子推理](../../../../tutorials/eef_action_space.md)

含旧`/tj/dm_sensor/...`完整场的oct03包用[腕部＋触觉＋机器人回放](../../../../tutorials/wrist_bag_review.md)：
独立domain93，读取命名修正版模型。新的grid话题包使用上面的小矩阵入口，不能只按录制日期选择。

新增[Stand关节方向修正版](../../../../tutorials/corrected_stand_review.md)：新支架与完整网格，修正角度约定；TCP/限位未验收。

新增[新外观＋旧运动链对照](../../../../tutorials/hybrid_urdf_review.md)：保留旧关节链，新网格逐件配准，不确定部分回退旧外观。

新增[Stand URDF 对照回放](../../../../tutorials/stand_urdf_review.md)：独立新模型入口，区分 L7 原点与录包 EEF，未校准。

新增[录包BC训练与ROS影子推理](../../../../tutorials/bag_bc_shadow.md)：只输出诊断预测，不控制机械臂；
短包验证只证明训练和推理链路跑通。

换机器先看[额外拷贝与安装清单](../../../../tutorials/machine_transfer_checklist.md)，按功能准备SDK、bag、基准和消息源码。

新SDK原生字段看板见[原生数值看板](../../../../tutorials/sdk_native_dashboard.md)：独立入口，旧看板保持不动。

旧record010可选[机器人文字状态同屏](../../../../tutorials/robot_state_dashboard.md)，
或[RViz双臂3D回放](../../../../tutorials/robot_3d_replay.md)：机器人命令只读，不回放控制话题。
带原生触觉场与末端的新ZIP/录包，使用同教程的 `view_recorded_observation_3d.sh` 独立入口；
末端与模型尚未标定对齐，不能拿显示位置当作已验证TCP。

独立 ROS 相机/触觉采集、录包、回放与双发行版安装见[传感器采集](../../../../tutorials/sensor_collection.md)。
触觉图像重建的 SDK 本地归档、跨机器数值/箭头对照见[重建复现教程](../../../../tutorials/tactile_reconstruction_migration.md)。

磁盘经验存储和图像吞吐测试见 [磁盘回放](../../../../tutorials/disk_replay.md)。

建议顺序：[重建环境](../../../../tutorials/environment_setup.md) → [最短仿真案例](../../../../tutorials/quickstart.md) → [A 臂任务](../../../../tutorials/a_arm_simulation.md) → [键盘示范](../../../../tutorials/keyboard_demonstration.md) → [策略运行中干预](../../../../tutorials/interactive_intervention.md) → [录制与回放](../../../../tutorials/recording_and_replay.md)。真机阶段先看[硬件准备](../../../../tutorials/hardware_preflight.md)，再运行[ROS 观测接口](../../../../tutorials/ros_observation_interface.md)；两者都没有真机运动命令。遇到问题见 [排障](../../../../tutorials/troubleshooting.md)。

所有命令从 `omi_proj/` 执行。`SCENE` 需由操作者改为自己机器上完整的 MJCF 路径。
- [触觉24×16低带宽发布](../../../../tutorials/tactile_grid_transport.md)：独立可选数值场，不改变旧看板默认流程。

- [录制末端位姿→动作增量→右臂回放与比较](../../../../tutorials/eef_pose_replay.md)

- [右臂六维增量画半径3cm圆](../../../../tutorials/circle_test.md)

- [本地 marvin_msgs 消息包：加载、迁移与重建](../../../../tutorials/marvin_messages.md)

- [手柄六维控制与 RB 接管](../../../../tutorials/gamepad_control.md)：摇杆/十字键映射、预览和真机发布、策略候选接口。

- [机器人接收端与手柄启动步骤](../../../../tutorials/robot_gamepad_startup.md)：OpticalModule A 臂连接、反馈检查、手柄预览与发布，含 Python 环境修正。

- [其他电脑复现手柄控制（Agent手册）](../../../../tutorials/gamepad_reproduce_on_other_pc.md)：固定提交、最小文件包、环境、跨机ROS和验收。
