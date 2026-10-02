# Hardware 当前摘要

新增[相机与触觉合并模式](evolution/tactile-live.md#相机与触觉合并模式)：一个播放器、一个
RViz Image，同时显示两路原图/128 ROI 和 A/B raw/deformation/shear。各路保留自己的
时间戳与过期提示，不代表跨传感器逐帧同步。最新自动测试为 59 passed、1 skipped；
运行证据见[合并显示编年](chronicles/2026-10-02-camera-tactile-dashboard.md)。

`TianjiSdkArm` 已封装 SDK A/B 反馈索引、度/弧度换算、反馈帧与错误检查、显式运动授权、单步和关节范围检查、位置模式与停止/释放。假 SDK 与 MuJoCo 替身测试通过；没有设备只读连接记录，没有真机运动验收。项目也没有面向操作者的真机控制 CLI。

`real` 包新增只读 ROS 2 观测接口，订阅 A 臂反馈、夹爪、外部/腕部 RGB 与双指触觉 raw/depth/force，按 header 时间对齐并输出固定 shape 的 Gym/NumPy/Torch 输入。两路 RGB 使用固定大小的正方形 ROI；头部 ROI 的逐帧像素偏移进入 observation，Wrist ROI 横向固定居中且不传偏移。`record010` 在 10 Hz 下离线生成 269 个有效 observation、0 个过期拒绝。该 observation 接口没有 publisher、动作执行、reward 或 episode 环境，不构成真机 RL 闭环。

同级相机辅助工具已提供原图/128 ROI、独立 512 放大和双版 RViz 模式，并保留最初单进程
入口。双版显示负载更高；追求流畅时使用原始单版。可视化不进入策略 observation，且当前
可视化与 observation 的 resize 算法不同。触觉已有 raw/depth/双指 12 维 wrench 输入，
另有[实时触觉回放工具](evolution/tactile-live.md)，发布 deformation/shear 数值 topic，
独立进程生成供 RViz 使用的 raw/向量 dashboard。`tactile_baseline` 已从 `record010` 的
`25–26 s` 完全张开窗口生成 A/B 的 `270×360 uint8` 时间中位数基准和验证报告；五项
零载荷启发式检查通过。bag 未记录 A/B 的厂商序列号，但底层 CPU `FlowTracker` 的
deformation/shear 重建不需要 serial，已在 23、25.5 和 28 秒完成离线探针。
操作者已确认右侧为逻辑 A / `X26040546`，左侧为逻辑 B / `X26040345`；确认映射已写入
新版基准和离线结果 metadata，但原始 bag 本身仍没有身份字段。
OMI 已有固定采样、固定 scale/deadband、显式 clipping 的 `H×W×2` 箭头 renderer，并通过
零场、`+x`、`-y`、截断和非有限值测试；bag 回放数值发布与 dashboard 已验证，RViz
交互和真机在线仍需验收。这里的 deformation 是触觉纹理相对零载荷基准的二维稠密
位移场；shear 是厂商 `Decomposer` 从 deformation 派生的剪切/旋转/滑动相关二维场。
两者单位均未完成物理标定，不能称为力场，也不能把箭头长度解释为牛顿。

当前 API 与限制见 [Tianji 适配器](evolution/tianji-adapter.md)与[ROS 观测接口](evolution/ros-observation.md)；形成阶段见[编年记录](chronicles/README.md)。近期需要在线 ROS 只读验收、现场设备配置和控制边界设计。
