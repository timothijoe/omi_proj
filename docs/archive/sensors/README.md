# 传感器历史

保留原始图、数值场、设备侧身份、基线、腕部ROI／共享内存／解耦和时钟诊断过程。字段可见、接收率与物理同步是不同证据；外部相机10月24日事故详见经验池归档。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/sensors.md)。

## 阶段记录

- [2026-10-02：ROS 多模态观测接口与 record010 验证](records/hardware/chronicles/2026-10-02-ros-observation.md)
- [2026-10-02：独立 ROS 传感器采集、录包与回放](records/hardware/chronicles/2026-10-02-sensor-collection.md)
- [2026-10-02：触觉 deformation/shear 字段语义与实现边界](records/hardware/chronicles/2026-10-02-tactile-field-semantics.md)
- [2026-10-02：双指逻辑侧与 serial 外部确认](records/hardware/chronicles/2026-10-02-tactile-identity-confirmation.md)
- [2026-10-02：rosbag 实时触觉向量回放](records/hardware/chronicles/2026-10-02-tactile-live-replay.md)
- [2026-10-02：record010 无 serial 离线触觉场重建](records/hardware/chronicles/2026-10-02-tactile-offline-reconstruction.md)
- [2026-10-02：触觉图像重建适配器与 SDK 本地归档迁移](records/hardware/chronicles/2026-10-02-tactile-reconstruction-migration.md)
- [2026-10-02：触觉分辨率、预训练编码与30 Hz采集讨论](records/hardware/chronicles/2026-10-02-tactile-resolution-and-throughput.md)
- [2026-10-02：触觉表示名称统一](records/hardware/chronicles/2026-10-02-tactile-terminology.md)
- [2026-10-02：OMI 触觉向量箭头 renderer](records/hardware/chronicles/2026-10-02-tactile-vector-renderer.md)
- [2026-10-02：record010 零载荷触觉基准提取](records/hardware/chronicles/2026-10-02-tactile-zero-load-baseline.md)
- [2026-10-03：腕部真实出图与视频流卡顿遗留](records/hardware/chronicles/2026-10-03-daimon-live-stream-stutter.md)
- [2026-10-03：真实触觉接通与腕部实时入口](records/hardware/chronicles/2026-10-03-daimon-live.md)
- [2026-10-03：共享内存结论边界与策略ROI传输方案](records/hardware/chronicles/2026-10-03-roi-stream-plan.md)
- [2026-10-03：传感器教程三件套](records/hardware/chronicles/2026-10-03-sensor-tutorial-triad.md)
- [2026-10-03：触觉深度与六维力启动开关](records/hardware/chronicles/2026-10-03-tactile-depth-wrench-flags.md)
- [2026-10-03：触觉数值场24×16可选传输](records/hardware/chronicles/2026-10-03-tactile-grid-transport.md)
- [2026-10-03：独立触觉采集默认改为低带宽完整数值输入](records/hardware/chronicles/2026-10-03-tactile-numeric-default.md)
- [2026-10-03：bag_004腕部回放、ROI基线及采集遗留](records/hardware/chronicles/2026-10-03-wrist-roi-and-capture-followup.md)
- [2026-10-03：腕部原图/ROI发布开关](records/hardware/chronicles/2026-10-03-wrist-roi-topic.md)
- [2026-10-03：腕部大图共享内存传输实验](records/hardware/chronicles/2026-10-03-wrist-shm-trial.md)
- [2026-10-03：视频流问题排查与解决过程归档](records/hardware/chronicles/2026-10-03-wrist-stream-investigation-summary.md)
- [2026-10-03：腕部相机准确话题名称核查与议题暂缓](records/hardware/chronicles/2026-10-03-wrist-topic-question.md)
- [2026-10-05：外部RGB时钟与接收年龄排查](records/hardware/chronicles/2026-10-05-rgb-clock-and-receive-age.md)
- [2026-10-05：触觉独立字段与腕部录制队列](records/hardware/chronicles/2026-10-05-sensor-decoupling.md)
- [2026-10-07：实时grid看板外部RGB按接收时间显示](records/hardware/chronicles/2026-10-07-grid-camera-receive-freshness.md)
- [2026-10-03：完成tactile和bc迁移，保留eef_bc](records/training/chronicles/2026-10-03-tactile-bc-archive-complete.md)
- [2026-10-03：腕部策略输入与相机可用性标记](records/training/chronicles/2026-10-03-wrist-policy-input.md)
- [2026-10-11：待改项——触觉编码器训练与长回合奖励折扣](records/training/chronicles/2026-10-11-tactile-gamma-pending.md)

## 原机制与领域摘要

- [ROS 多模态观测接口](records/hardware/evolution/ros-observation.md)
- [独立传感器采集与回放](records/hardware/evolution/sensor-collection.md)
- [触觉与腕部采集解耦：实现方法与边界](records/hardware/evolution/sensor-decoupling.md)
- [RGB与触觉的时间基准、接收新鲜度和策略检查](records/hardware/evolution/sensor-time-alignment.md)
- [rosbag 播放时的触觉向量显示](records/hardware/evolution/tactile-live.md)
- [图像重建接口迁移：当前方案](records/hardware/evolution/tactile-reconstruction-migration.md)
- [触觉分辨率、策略编码与采集吞吐](records/hardware/evolution/tactile-resolution-and-throughput.md)
- [腕部视频流卡顿：排查、传输改善与ROI发布](records/hardware/evolution/wrist-stream-performance.md)

## 其他原文

- [双相机 ROI 选择约定：第一版](design/camera-roi-v1.md)
- [真机触觉观测、录制与可视化验证需求](design/tactile-observation-requirements.md)

外部相机断流的训练影响见[20回合清理记录](../replay/records/training/chronicles/2026-10-24-external-camera-outage-cleanup.md)。
