# 2026-10-02：record010 无 serial 离线触觉场重建

## 目标

验证 A/B serial 是否真的是 deformation/shear 离线重建的前置条件，并在不连接设备的边界
内从 `record010` raw 生成数值矩阵和人工 dashboard。

## 实际实现

建立被 Git 忽略的 `local/venvs/daimon312`，使用 Python 3.12、系统 OpenCV/NumPy 和新增
`h5py`。Daimon SDK 与 PyArmor 运行时导入通过。没有构造 `Sensor`；直接使用底层 CPU
`FlowTracker` 设置 A/B 中位数 base，随后调用 `Decomposer` 和 `NormalFromFlowCached`。

新增 `real.tactile_offline`，从 bag 为目标时刻选择最近 raw/depth/wrench，保存数值 NPZ、
固定参数箭头 PNG、双指 dashboard 和 JSON 报告。工具拒绝覆盖已有目录。

## 验证证据

- deformation/shear 输出均为 `288×384×2 float32`，不需要 serial。
- base 自身输出严格全零；25.5 秒松开帧 B 全零，A 仅有小量残差。
- 23 和 28 秒两侧均得到结构化接触向量场，OMI renderer 已实际绘制。
- 接触帧重建 depth 与 bag depth 的 Pearson 相关为 0.907–0.951。
- 最小二乘比例约 0.44–0.47，说明默认离线 depth 幅值约为在线记录的两倍。
- 专项测试 `10 passed`；完整测试 `50 passed, 1 skipped`。

## 限制与影响

record010 没有 deformation/shear topic，无法逐元素对照录制时在线矩阵；shear 的物理方向
也尚未通过人工已知方向按压验收。depth 的空间一致性支持 raw/base 路径有效，但幅值差异
表明在线 producer 可能使用不同参数或缩放。serial 不再阻塞 deformation/shear 原型，
仍需用于设备追溯及可能的 force/标定模型选择。当前结果只在本地文件中，尚未发布 ROS
数值 topic 或 RViz dashboard。
