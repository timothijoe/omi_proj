# 操作教程

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
