> 历史资料：原路径 `docs/agent/hardware/chronicles/2026-10-17-apriltag-follow-migration.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/marker.md)；本页保留原过程与证据。

# 2026-10-17 AprilTag 位姿估计与跟随源码迁入

用户要求先将 `Downloads/oct17` 中两个文件迁入项目，后续再适配。本轮采用原样复制，保留 Downloads 原件。

| 文件 | 正式位置 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| tag_pose.py | `ros2/marker_detect/tag_pose.py` | 20978 | `22f955e6b7a872328cb20881a4c7e6df5b8c6b1bc1be3d89d80f12c385d637dc` |
| tag_follow_tag_v2.py | `ros2/marker_detect/tag_follow_tag_v2.py` | 13631 | `6552ff95bbd37f50f923968ec5035ca2cca0b46e015822819e6c4ac67e0eff89` |

原始备份及 `source_sha256.json` 保存在 `local/vendor/apriltag_follow/oct17/`，受现有 `local/` 忽略规则覆盖。正式文件与来源、备份哈希一致；使用 Python 内置 `compile` 完成两文件语法检查，没有导入或执行其顶层代码。

未修改算法、控制参数或导入路径，未运行设备。缺少 `handeye_solver.py` 与配套 X/Z 标定、旋转向量与 SDK ABC 差异、直接相机采集和运行停止边界留待下一阶段，详见[当前能力与适配事项](../evolution/apriltag-follow.md)。原有 SpacePilot 等工作区改动保留。
