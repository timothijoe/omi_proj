# 机器人控制历史

从SDK边界和动作接口推进到ROS接收端、速度保持、触觉保护及真实响应排查。控制回执和SDK提交不等于实际完成；10月17日拖尾和SDK忙证据仍有未解决边界。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/control.md)。

## 阶段记录

- [2026-10-01：SDK 边界与模拟测试](records/hardware/chronicles/2026-10-01-sdk-boundary.md)
- [2026-10-05 手柄、策略速度保持与夹爪启用修复](records/hardware/chronicles/2026-10-05-control-velocity-hold.md)
- [2026-10-05：OpticalModule 控制接收端迁移](records/hardware/chronicles/2026-10-05-robot-controller-migration.md)
- [2026-10-07：左臂 EEF 安装平移修正与实时显示补偿移除](records/hardware/chronicles/2026-10-07-eef-mount-and-view.md)
- [2026-10-04：核对 axis_test 实机接口](records/training/chronicles/2026-10-04-axis-controller-interface.md)
- [2026-10-04：暂定基坐标系旋转向量与转换说明](records/training/chronicles/2026-10-04-axis-rotation-assumption.md)
- [2026-10-09：首次新仲裁试跑的 SDK 拒绝与通道切换排查](records/training/chronicles/2026-10-09-sdk-rejection-and-handoff-audit.md)

## 原机制与领域摘要

- [OpticalModule 控制架构与接收端迁移](records/hardware/evolution/robot-controller.md)
- [Tianji SDK 适配器](records/hardware/evolution/tianji-adapter.md)
- [对齐 axis_test 实机动作接口](records/training/evolution/axis-controller-interface.md)
- [Policy 动作缩放策略与讨论结论](records/training/evolution/policy-action-scaling.md)
