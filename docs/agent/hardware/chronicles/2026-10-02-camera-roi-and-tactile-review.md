# 2026-10-02：相机 ROI 双版本可视化与触觉输入核查

## 目标

核对真机 observation 中的相机 ROI 和触觉数据链，建立可人工检查的 RViz 图像，并评估
Daimon 触觉形变箭头是否应进入策略网络。本阶段只读取 rosbag 和源码，不连接控制器、
不发布运动命令。

## 实际实现

工作区同级 `ros2_camera_clip_tools/` 使用与 `record010` 对应的固定头部和 Wrist ROI，发布
两路 `128×128 rgb8` clip 和原图/clip 四宫格。随后增加独立的 512 可视化进程：它订阅
两路 128 clip，以最近邻上采样到 `512×512`，发布单图及双图 dashboard；放大图只用于
RViz，不改变 OMI observation。

最终保留三种显示模式：`observation` 只运行第一版，`512` 由第一进程产生 128 clip、
第二进程放大后只显示第二版，`both` 以两个处理进程同时产生两版 dashboard。由于双
dashboard 同时解码和渲染明显增加负载，另保留
`view_camera_clip_original.sh`：一个裁剪进程、一个 RViz Image、Reliable/depth 5，行为与
最初的原图加 128 clip 版本一致。普通多模式入口使用 BEST_EFFORT/depth 1，避免 RViz
积压旧帧。

OMI 真机 observation 本身仍直接订阅两路原图并在进程内裁剪，不订阅上述可视化 topic。
两边 ROI 几何参数一致，但可视化工具使用 Lanczos，observation 当前使用最近邻，因此不能
声称两者像素级相同。

触觉核查确认现有 observation 订阅双指 raw、depth 和六维 wrench：输出双指
`tactile_raw (64,64,2)`、`tactile_depth_delta (64,64,2)` 和基线差分后的
`wrench_delta (12,)`。`record010` 中 raw 为 `mono8 360×270`，depth 为
`32FC1 384×288`。本地 Daimon 示例另有 `H×W×2` deformation/shear 和箭头可视化，
但 bag 与 OMI topic 契约中没有这两类数据。箭头图带有空间采样、阈值、缩放和绘制损失，
只适合人工观察；若以后引入策略，应优先保存归一化的稠密向量张量并由 CNN 编码，而不是
把箭头栅格图作为网络输入。该方向是设计建议，尚未实现或训练验证。

## 验证证据

- `record010` 的 29.74 秒 bag 含头部约 28 Hz、Wrist 约 10 Hz 图像；Wrist 原始频率限制了
  双图 dashboard 的视觉流畅度。
- 用 `ros2 bag info` 和只读 `rosbag2_py` 解码确认四路触觉图像的类型、分辨率与编码。
- 真机 observation 专项测试为 `8 passed`。
- 相机工具通过 Python 编译、Shell 语法、三个 RViz YAML 解析和 Launch 参数检查。
- headless rosbag 冒烟检查确认独立 512 进程能消费 128 clip，并发布宽 1044 的双图
  dashboard。用户人工运行 RViz 后确认两版能显示，同时反馈双 Image 模式较最初单版更慢。

## 限制与影响

没有在真实在线 ROS 图或真机相机上验收频率、QoS 和长期稳定性；没有测量 RViz CPU/GPU、
DDS 带宽或端到端延迟。BEST_EFFORT 会主动丢弃旧帧，适合诊断画面，不可据此评价策略
observation 是否丢帧。双版模式仍要求 RViz 同时渲染两张大型未压缩 dashboard；追求流畅
时应使用保留的原始单版入口。

本阶段没有加入 deformation/shear ROS topic、触觉 dashboard、视觉策略、动作、奖励或
真机 RL 闭环。后续若推进触觉策略，应先以状态、双指 12 维 wrench 和 depth delta 建立
基线，再用消融实验决定是否增加稠密 deformation/shear。
