# 操作教程

- [历代 RViz 回放：三包与完整一行式命令](rviz_representative_bags.md)

- [真机RL人工回合：按钮成功、超时停止、手柄复位和连续采集](rl_episode_collection.md)

- [当前无wrench模型：推理、RB接管、Ctrl+C观测保存](no_wrench_policy_record.md)

- [独立传感器采集、腕部可靠录制与时间审计](sensor_decoupling.md)

- [新wrench BC模型真机入口：默认预览、RB手柄优先](wrench_policy_gamepad.md)

- [本次日期bag转训练集：双指六维力/力矩BC训练](passive_bag_bc_wrench.md)

- [独立手柄录包、四包检查、真实指令预览与左右键切帧](demo_bag_dataset.md)

- [集成手柄 Demo 采集、发送指令标签与 BC](demo_collection_bc.md)

- [六维真机HIL环境、无夹爪SAC与Actor/Learner](hil_actor_learner.md)

- [USB 插入触觉保护：峰值锁定和负 X 撤退](tactile_guard.md)
- [只读触觉预警：读取原始示数，超限打印日志](tactile_warning.md)
- [双指六维力/力矩：实时查看和完整历史记录](wrench_live.md)

- [机器人控制接收端：速度保持、参数、重启与离线预览](robot_controller.md)

- [无关节模型实时 ROS 影子推理](stack_shadow.md)

- [实时相机、触觉与末端位姿RViz看板](grid_live_review.md)


- [不使用关节反馈的GPU训练](nojoint_stack_training.md)


- [六关键点候选与人工审核工具](six_keypoint_review.md)

- [当前帧独立＋过去9帧通道拼接训练](current_stack_history.md)

- [冻结ResNet-10历史策略训练与对照](resnet10_history.md)

- [历史 policy 在线推理与 wrench 开关](eef_history_online.md)

- [oct3正式录包检查、学习格式转换与训练](oct3_formal_dataset.md)

传感器常用操作优先看三个互相索引的教程：

- [腕部＋触觉常用命令速查](sensor_commands.md)
- [腕部相机专项](wrist_camera.md)
- [触觉专项：小矩阵、raw/wrench开关与录包](tactile_grid_transport.md)

默认参数、topic和常用命令变更时，三份文件共同维护。

- [24×16触觉＋腕部ROI＋3D机器人通用回放](grid_bag_review.md)：用于新的`/omi/tactile_grid24x16/...`录包。

- [末端动作 rosbag、Float64MultiArray 与模拟控制端联调](eef_action_bag.md)

- [戴蒙触觉与腕部相机独立实时启动、RViz及时延检查](daimon_live.md)

- [bag_004末端动作空间、BC与类型化影子推理](eef_action_space.md)

含旧`/tj/dm_sensor/...`完整场的oct03包用[腕部＋触觉＋机器人回放](wrist_bag_review.md)：
独立domain93，读取命名修正版模型。新的grid话题包使用上面的小矩阵入口，不能只按录制日期选择。

新增[Stand关节方向修正版](corrected_stand_review.md)：新支架与完整网格，修正角度约定；TCP/限位未验收。

新增[新外观＋旧运动链对照](hybrid_urdf_review.md)：保留旧关节链，新网格逐件配准，不确定部分回退旧外观。

新增[Stand URDF 对照回放](stand_urdf_review.md)：独立新模型入口，区分 L7 原点与录包 EEF，未校准。

新增[录包BC训练与ROS影子推理](bag_bc_shadow.md)：只输出诊断预测，不控制机械臂；
短包验证只证明训练和推理链路跑通。

换机器先看[额外拷贝与安装清单](machine_transfer_checklist.md)，按功能准备SDK、bag、基准和消息源码。

新SDK原生字段看板见[原生数值看板](sdk_native_dashboard.md)：独立入口，旧看板保持不动。

旧record010可选[机器人文字状态同屏](robot_state_dashboard.md)，
或[RViz双臂3D回放](robot_3d_replay.md)：机器人命令只读，不回放控制话题。
带原生触觉场与末端的新ZIP/录包，使用同教程的 `view_recorded_observation_3d.sh` 独立入口；
末端与模型尚未标定对齐，不能拿显示位置当作已验证TCP。

独立 ROS 相机/触觉采集、录包、回放与双发行版安装见[传感器采集](sensor_collection.md)。
触觉图像重建的 SDK 本地归档、跨机器数值/箭头对照见[重建复现教程](tactile_reconstruction_migration.md)。

磁盘经验存储和图像吞吐测试见 [磁盘回放](disk_replay.md)。

建议顺序：[重建环境](environment_setup.md) → [最短仿真案例](quickstart.md) → [A 臂任务](a_arm_simulation.md) → [键盘示范](keyboard_demonstration.md) → [策略运行中干预](interactive_intervention.md) → [录制与回放](recording_and_replay.md)。真机阶段先看[硬件准备](hardware_preflight.md)，再运行[ROS 观测接口](ros_observation_interface.md)；两者都没有真机运动命令。遇到问题见 [排障](troubleshooting.md)。

所有命令从 `omi_proj/` 执行。`SCENE` 需由操作者改为自己机器上完整的 MJCF 路径。
- [触觉24×16低带宽发布](tactile_grid_transport.md)：独立可选数值场，不改变旧看板默认流程。

- [录制末端位姿→动作增量→右臂回放与比较](eef_pose_replay.md)

- [右臂六维增量画半径3cm圆](circle_test.md)

- [本地 marvin_msgs 消息包：加载、迁移与重建](marvin_messages.md)

- [手柄六维控制与 RB 接管](gamepad_control.md)：摇杆/十字键映射、预览和真机发布、策略候选接口。

- [机器人接收端与手柄启动步骤](robot_gamepad_startup.md)：OpticalModule A 臂连接、反馈检查、手柄预览与发布，含 Python 环境修正。

- [其他电脑复现手柄控制（Agent手册）](gamepad_reproduce_on_other_pc.md)：固定提交、最小文件包、环境、跨机ROS和验收。
