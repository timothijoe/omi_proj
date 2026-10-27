# 操作教程

按操作目的选择；先看[项目当前摘要](../docs/current.md)核对选定配置和任务。辅助工具有各自契约，不因仍可运行就成为主流程。

## 常用入口

- [SpacePilot BC6148：新任务与已有run续跑](spacepilot_bc6148_online_rl.md)
- [RViz V2：九幅观测图与末端／人工／策略bar](grid_live_review_v2.md)
- [Actor/Learner训练网页](training_monitor.md)
- [设备与动作入口速查](common_live_commands.md)
- [人工回合采集](rl_episode_collection.md)
- [缓存和完整会话恢复](cached_replay.md)

训练、设备采集和监控使用各自入口；按教程核对实际任务目录。

## 在线训练

- [SpacePilot BC6148 在线 RL：显式 setting 与旧配置对照](spacepilot_bc6148_online_rl.md)
- [按回合交替的真机 RL（2026-10-07 最小版本）](alternating_rl.md)
- [异步真机 RL：每 10 个完整回合检查新策略](async_rl.md)
- [真机常用启动指令汇总](common_live_commands.md)
- [六维真机 HIL 环境、SAC 与 Actor/Learner](hil_actor_learner.md)
- [真机RL：人工回合采集与复位](rl_episode_collection.md)
- [机器人接收端与手柄启动步骤](robot_gamepad_startup.md)

## 示范与BC

- [录包 → BC初始策略 → ROS影子推理](bag_bc_shadow.md)
- [独立手柄录包、数据检查与逐帧可视化](demo_bag_dataset.md)
- [集成手柄 Demo 采集、指令标签与 BC](demo_collection_bc.md)
- [日期 bag → 含双指六维力/力矩的 BC 训练](passive_bag_bc_wrench.md)

## 经验池与存储

- [双池内存缓存：全量数据留盘，后台加载训练](cached_replay.md)
- [使用磁盘经验池](disk_replay.md)
- [本机 local 与外接盘数据的使用](local_data_storage.md)
- [完整 transition 的磁盘存储与双流导入](transition_replay.md)

## 策略模型

- [bag_004：末端动作空间、BC与影子推理](eef_action_space.md)
- [历史 policy 在线推理与 wrench 开关](eef_history_online.md)
- [无关节模型：实时 ROS 影子推理](stack_shadow.md)

## 机器人控制

- [右臂六维增量画圆](circle_test.md)
- [真机准备：只读阶段](hardware_preflight.md)
- [OpticalModule 机械臂控制代码迁移](robot_controller.md)
- [USB 插入触觉保护](tactile_guard.md)
- [只读触觉阈值预警](tactile_warning.md)

## 人工输入

- [手柄控制、SDK 换轴与 RB 接管](gamepad_control.md)
- [SpacePilot 机械臂末端增量控制](spacepilot_control.md)
- [SpacePilot 用于 BC/RL 采集与在线交互](spacepilot_hil.md)
- [SpacePilot 六自由度物体操控](spacepilot_pose.md)

## 相机与触觉

- [戴蒙双指触觉与腕部相机实时预览](daimon_live.md)
- [真机 ROS 观测接口（只读）](ros_observation_interface.md)
- [独立 ROS 传感器：安装、采集、录包与回放](sensor_collection.md)
- [腕部相机＋触觉：常用命令速查](sensor_commands.md)
- [独立传感器采集、录制与时间审计](sensor_decoupling.md)
- [触觉24×16低带宽发布（可选第一版）](tactile_grid_transport.md)
- [在另一台机器恢复触觉重建并做可视化比对](tactile_reconstruction_migration.md)
- [腕部相机：采集、ROI/full与查看](wrist_camera.md)

## AprilTag

- [AprilTag：位姿记录、手眼标定与手柄跟随](marker_detect.md)

## 仿真

- [A 臂任务、训练与独立评估](a_arm_simulation.md)
- [策略运行中的键盘干预](interactive_intervention.md)
- [键盘录制 A 臂示范](keyboard_demonstration.md)
- [最短可运行仿真案例](quickstart.md)
- [录制、示范导入与可视化](recording_and_replay.md)

## 监控与可视化

- [Stand 关节方向修正版（只读可视化）](corrected_stand_review.md)
- [将录制的末端位姿转为增量并回放](eef_pose_replay.md)
- [小矩阵触觉＋腕部ROI＋机器人：通用RViz回放](grid_bag_review.md)
- [实时相机、触觉与末端位姿 RViz 看板](grid_live_review.md)
- [实时观测 V2：独立原图、触觉面板与延迟诊断](grid_live_review_v2.md)
- [新外观与旧运动链对照](hybrid_urdf_review.md)
- [真机 RL 回合逐帧可视化与人工检查](rl_episode_visual_review.md)
- [RViz双臂3D回放＋视觉触觉看板](robot_3d_replay.md)
- [旧录包：视觉、触觉与机器人状态同屏](robot_state_dashboard.md)
- [RViz 操作教程：实时传感器与历代录包](rviz_representative_bags.md)
- [SDK 原生数值看板](sdk_native_dashboard.md)
- [六关键点自动候选与人工审核](six_keypoint_review.md)
- [用新 Stand URDF 对照回放](stand_urdf_review.md)
- [Actor / Learner 统一训练监控](training_monitor.md)
- [双指六维力/力矩：实时查看与完整历史记录](wrench_live.md)
- [bag_004腕部相机＋触觉＋机器人RViz回放](wrist_bag_review.md)

## 环境与通用工具

- [仿真环境安装与激活](environment_setup.md)
- [在其他电脑复现手柄末端控制：Agent 执行手册](gamepad_reproduce_on_other_pc.md)
- [换机器：额外拷贝与重新安装清单](machine_transfer_checklist.md)
- [项目本地 marvin_msgs 消息包](marvin_messages.md)
- [当前操作：无六维力/力矩模型推理与观测录制](no_wrench_policy_record.md)
- [实时 policy、RB 接管与 SDK 输出](policy_gamepad.md)
- [排障、停止与恢复](troubleshooting.md)
- [Ubuntu 22.04：在线 RL 与人工回合采集的运行依赖](ubuntu2204_online_rl_dependencies.md)
- [带六维力/力矩的 BC 模型：预览与真机手柄接管](wrench_policy_gamepad.md)

固定日期／模型实验的旧教程已移到[模块归档](../docs/archive/README.md)，用于复现而不是日常默认命令。
