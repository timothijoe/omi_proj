# 历代 RViz 回放：本机三包操作页

## 目的与保留方案

本机只保留三种录包格式的代表样例，供旧触觉/相机、原生触觉/腕部、24×16 grid 及机器人模型对照入口检查。历史录包迁至移动硬盘；四个 2026-10-05 手柄 BC 示范包和 RL 回合数据不属于本次 RViz 精简范围。实时看板直接订阅现场 ROS 话题，不依赖下面三包。

| 格式与用途 | 本机实际文件 | 约占空间 |
| --- | --- | ---: |
| 旧 record010：相机、触觉重建、机器人状态与旧 3D | `/home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001/` | 1.6 GiB |
| 原生场 bag_004：腕部相机、触觉、EEF 与 Stand/Hybrid 对照 | `/home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip` | 1.2 GiB |
| grid24x16：腕部 ROI、双指三场、EEF 与修正版机器人 | `/home/zhoutong/omi_folder/representative_rosbag/october/grid24x16_bag_001.zip` | 281 MiB |

旧 Downloads 路径为指向上述本机文件的符号链接。其他历史 RViz 文件归档于 `/media/zhoutong/zt-think-d1/omi_rviz_archive_20261007/`；`manifest.json` 记录逐文件 SHA-256、原路径与归档路径。旧 Downloads 中部分未保留的包仍以符号链接指向移动硬盘，拔盘后这些历史链接不可用。本页三包本身位于本机，不依赖移动硬盘挂载。

## 完整命令

每行都是独立命令，可从任意工作目录执行；一次运行一个 RViz 入口，用 `Ctrl+C` 结束后再试下一条。各回放入口只发布显示所需的话题，不回放机器人控制命令。

| 显示版本 | 直接复制运行的命令 |
| --- | --- |
| 当前 grid＋3D | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_grid_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/grid24x16_bag_001.zip` |
| 腕部相机＋触觉＋3D | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_wrist_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip` |
| 原生触觉＋旧3D | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_recorded_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip` |
| 方向修正版 Stand | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_corrected_stand_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar` |
| Hybrid 模型 | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_hybrid_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar` |
| 原版 Stand | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_stand_observation_3d.sh /home/zhoutong/omi_folder/representative_rosbag/october/native_wrist_bag_004.zip /home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar` |
| 早期机器人3D | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_observation_robot_3d_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001` |
| 早期机器人文字状态 | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_observation_robot_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001` |
| 早期相机＋触觉 | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_observation_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001` |
| 早期纯触觉 | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_tactile_bag.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001` |
| 迁移版触觉重建 | `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_observation_bag_migrated.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001` |
| 早期相机 ROI | `bash /home/zhoutong/omi_folder/ros2_camera_clip_tools/view_camera_clip.sh /home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001 1.0 observation` |

`view_camera_clip.sh` 的第三个参数还可改为 `512` 或 `both`。以上旧入口仍只使用同一份 record010 样例。

实时版本直接订阅现场话题，不读取上述三个 bag；对应完整命令为 `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_grid_observation_live.sh` 和 `bash /home/zhoutong/omi_folder/omi_proj/scripts/view_sdk_observation.sh`。原生 SDK 看板默认只启动订阅与显示，现场采集需另行启动，详情见[原生 SDK 看板教程](sdk_native_dashboard.md)。

## 数据与依赖边界

- record010 保留 `metadata.yaml` 与其引用的 `.mcap.zstd`；本机的未压缩 MCAP 副本已经归档。旧触觉重建还使用 `omi_proj/local/tactile/record010_zero_load_25_26_confirmed_v2/` 和 Daimon SDK。零载荷基准在本次检查中按原包 25–26 秒窗口重建并通过记录用检查；它不是力标定。
- Stand 与 Hybrid 命令还需要上述原版 RAR；该模型资源不属于三个 bag。命名修正版资源保留在 `omi_proj/local/models/omi_marvin_stand_axis_corrected_v1/`。机器人模型、EEF/TCP、限位尚未完成现场标定，只用于显示。
- `native_wrist_bag_004.zip` 的腕部画面在原始录包中近乎静止；`grid24x16_bag_001.zip` 的 wrench 话题计数为零。它们可验证各自回放链路，不能用于验收腕部运动画面或 wrench 动态效果。
- 本次从新路径重新生成了旧 record010 的机器人时间线/触觉缓存、bag_004 的原生与腕部缓存、grid 缓存；三个 ZIP 的 CRC 检查、录包格式与此前无 GUI ROS 启动检查通过。此次路径调整没有逐个打开 RViz 窗口人工目测。证据与迁移步骤见[2026-10-07 编年](../docs/agent/hardware/chronicles/2026-10-07-rviz-bag-relocation.md)。
