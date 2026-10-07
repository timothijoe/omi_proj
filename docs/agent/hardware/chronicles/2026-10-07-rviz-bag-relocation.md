# 2026-10-07：RViz代表录包集中与历史文件外置

## 目的

此前 RViz 回放分散使用 record010、原生场 bag、grid bag 和多种机器人模型对照入口；本机 Downloads 与项目 `local/bags/oct03` 同时保存 ZIP、解压文件及重复副本。用户希望本机保留约 2–3 个能覆盖历代回放的样例，其余历史录包迁至移动硬盘，减少占用并提供可直接复制的一行式命令。

## 选择与实施

三包分别覆盖互不兼容的旧重建触觉、原生触觉/腕部、24×16 grid 话题格式，实际位置均在 `/home/zhoutong/omi_folder/representative_rosbag/october/`：

| 本机样例 | 覆盖入口 | 大小 |
| --- | --- | ---: |
| `record010/bag_001/` | 旧相机/触觉合并、迁移版重建、机器人文字/旧3D、相机 ROI 辅助工具 | 约1.6 GiB |
| `native_wrist_bag_004.zip` | 原生字段＋旧3D、腕部版、原版 Stand、Hybrid、方向修正版 Stand | 约1.2 GiB |
| `grid24x16_bag_001.zip` | 新 grid＋腕部 ROI＋机器人3D | 约281 MiB |

先逐话题核对候选包、检查三个 ZIP 完整性，准备缓存并在隔离 ROS 域做无 GUI 启动检查。发现 record010 旧看板缺少零载荷基准后，从该包 25–26 秒窗口重建，记录用零载荷检查通过。Hybrid 模型生成较慢；短时测试先在准备阶段超时，随后加长限时后成功生成模型并进入播放。`bag_004` 生成原生与腕部缓存，grid 包生成全部双相机/三场/关节/EEF缓存。清理后又从新的三包路径重新生成对应缓存；record010 仅保留 metadata 与压缩 MCAP，`ros2 bag info` 及旧入口重新启动通过。

本次验证边界是输入内容、缓存生成和无 GUI 发布链启动；没有逐个打开 RViz GUI 进行人工视觉验收。`bag_004` 腕部画面在源数据中近乎静止，grid 包 wrench 计数为零。实时 RViz 看板订阅现场话题，不由这三包代表。

## 归档与路径

历史文件归档到移动硬盘 `/media/zhoutong/zt-think-d1/omi_rviz_archive_20261007/`。`manifest.json` 登记58个文件的源路径、目标路径、大小和 SHA-256；复制后逐文件比较、清理前再次比较，全部一致才移除本地物理副本。归档共约33.23 GiB，其中包含 record010 未压缩 MCAP；本机可用空间约从76 GB升至106 GB。移动硬盘归档是完整历史副本，不是当前三包的唯一保存位置。

三包通过同一文件系统内移动集中到 `representative_rosbag/october/`，对每个样例做移动前后 SHA-256 对比。旧 Downloads 路径保留指向新样例的符号链接；其他历史 Downloads 文件保留指向移动盘的符号链接，因此外置文件在移动盘未挂载时不可用。项目内 `local/bags/oct03` 的重复副本已清出；2026-10-05 四个手柄 BC 示范包和 RL 回合数据没有纳入迁移。本次没有改动 RViz 程序、ROS 话题或机器人控制。

当前操作入口与全部完整命令见[三包 RViz 操作页](../../../../tutorials/rviz_representative_bags.md)。功能现状和模型差异见[机器人回放纪传体](../evolution/robot-3d-replay.md)，资源定位见[本地资源接口](../../interfaces/local-resources.md)。
