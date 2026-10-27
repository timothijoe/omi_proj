# 监控与可视化历史

从离线录包／旧实时整图看板演变到训练网页与独立RViz V2。10月24日V2完成九图、ROI过期标记、停靠修复和EEF／人工／策略三列bar；统一健康后台仍是设计。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/visualization.md)。

## 阶段记录

- [2026-10-02：相机 ROI 双版本可视化与触觉输入核查](records/hardware/chronicles/2026-10-02-camera-roi-and-tactile-review.md)
- [2026-10-02：相机和触觉合并显示](records/hardware/chronicles/2026-10-02-camera-tactile-dashboard.md)
- [2026-10-02：新录包检查、原生字段看板与末端坐标核查](records/hardware/chronicles/2026-10-02-native-record-review.md)
- [2026-10-02：从文字状态到RViz双臂3D回放](records/hardware/chronicles/2026-10-02-robot-3d-replay.md)
- [2026-10-02：旧录包机器人状态同屏](records/hardware/chronicles/2026-10-02-robot-state-dashboard.md)
- [2026-10-02：独立 SDK 原生数值看板](records/hardware/chronicles/2026-10-02-sdk-native-dashboard.md)
- [2026-10-02：保护稳定看板及 ROS→策略输入核查](records/hardware/chronicles/2026-10-02-stable-viewer-policy-audit.md)
- [2026-10-02：触觉预览与原图布局调整](records/hardware/chronicles/2026-10-02-tactile-preview-layout.md)
- [2026-10-02：腕部相机需求澄清与可视化遗留](records/hardware/chronicles/2026-10-02-wrist-viewer-followup.md)
- [2026-10-03：小矩阵实录回放、raw缺失解释与开发暂缓](records/hardware/chronicles/2026-10-03-grid-bag-review-and-raw-deferred.md)
- [2026-10-03：通用小矩阵RViz回放入口](records/hardware/chronicles/2026-10-03-grid-general-viewer.md)
- [2026-10-03：Stand 模型对照、关节方向修正与命名归档](records/hardware/chronicles/2026-10-03-stand-axis-correction.md)
- [2026-10-04：实时grid观测RViz看板](records/hardware/chronicles/2026-10-04-grid-live-review.md)
- [2026-10-04：实时 RViz 阶段总结与 EEF 对齐遗留](records/hardware/chronicles/2026-10-04-live-rviz-checkpoint.md)
- [2026-10-05：双指六维力/力矩实时显示与历史记录](records/hardware/chronicles/2026-10-05-wrench-live-recording.md)
- [2026-10-07：RViz代表录包集中与历史文件外置](records/hardware/chronicles/2026-10-07-rviz-bag-relocation.md)
- [2026-10-24：独立原图与触觉面板V2](records/hardware/chronicles/2026-10-24-grid-live-review-v2.md)
- [2026-10-04：六关键点本地候选与人工审核闭环](records/training/chronicles/2026-10-04-six-keypoint-review.md)
- [2026-10-09：真机 RL 原始回合逐帧查看](records/training/chronicles/2026-10-09-rl-episode-visual-review.md)
- [2026-10-09：Actor / Learner 统一训练监控](records/training/chronicles/2026-10-09-training-monitor.md)
- [2026-10-11：原BC权重、新数据目录、30秒回合与双池可视化](records/training/chronicles/2026-10-11-30s-buffer-dashboard.md)

## 原机制与领域摘要

- [实时观测V2：独立面板与接收／绘图隔离](records/hardware/evolution/grid-live-review-v2.md)
- [实时小矩阵观测看板](records/hardware/evolution/grid-live-review.md)
- [机器人3D录包回放](records/hardware/evolution/robot-3d-replay.md)
- [SDK 原生数值看板](records/hardware/evolution/sdk-native-dashboard.md)
- [双指wrench实时显示与持久历史](records/hardware/evolution/wrench-live.md)
- [右臂录制位姿的动作转换与回放](records/training/evolution/recorded-pose-replay.md)
- [六关键点自动预标注与人工审核工具](records/training/evolution/six-keypoint-review.md)
- [统一训练监控：状态、链路与只读审阅](records/training/evolution/training-monitor.md)

统一监控后续计划见[当前设计](../../design/system-health-monitoring.md)。
