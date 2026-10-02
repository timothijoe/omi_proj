# 独立传感器采集与回放

实现：`ros2/omi_sensors/omi_sensors/`。独立 ament_python 包，Python >=3.10；
主 RL 包 Python >=3.12 的要求不变。安装/用法见[教程](../../../../tutorials/sensor_collection.md)。

## 职责

- `config.py`：严格 schema、设备配置、RealSense launch 参数、传感器 topic 白名单。
- `tactile.py`：延迟导入厂商 SDK；Flux getter 数值读取、同 fid 检查、数组复制和有限性校验。
- `node.py`：每指独立进程、同帧统一 header、状态/重试、SDK 原图与 infer 分离、模拟源。
- `cli.py`：plan/doctor/live/fake/record/replay；子进程组退出管理、录包版本/数量报告、私有解压。
- `reconstruction.py`：从原看板迁入的固定基准 CPU 图像重建；`vendor_bundle` 与 `reconstruction_check` 提供归档/回归工具。
  见[迁移方案](tactile-reconstruction-migration.md)。

不调用参考工程、不启动控制节点、不发布动作。新硬件采集暂不包含腕部 gRPC 相机；
旧腕部相机 bag 保持允许回放。完整策略 observation 所需关节/夹爪反馈仍由已有只读接口提供。

## Topic 契约

| Topic | 类型 / 语义 |
| --- | --- |
| `/camera/camera/color/image_raw` | 官方驱动 Image 彩色图，默认 640×480×30 |
| `/camera/camera/color/camera_info` | 官方驱动 CameraInfo，不自行伪造实机内参 |
| `/omi/tactile/{a,b}/raw` | Image mono8/bgr8/bgra8，真正 `getRawImg()` 返回值 |
| `/omi/tactile/{a,b}/infer` | Image mono8/bgr8/bgra8，`getInferImg()` 的预处理图 |
| `/omi/tactile/{a,b}/deformation` | Image 32FC2，H×W×2 float32，SDK 位移场 |
| `/omi/tactile/{a,b}/shear` | Image 32FC2，H×W×2 float32，SDK 派生场 |
| `/omi/tactile/{a,b}/metadata` | String JSON schema 2：fid、host timestamp、identity、字段 shape/dtype、SDK 哈希、baseline 未知标记、丢帧数 |
| `/omi/tactile/{a,b}/status` | String JSON，每秒状态 starting/connecting/streaming/incomplete/retrying/synthetic 及错误 |
| `/omi/tactile/{a,b}/depth` | 可选 Image 32FC1，默认关闭、单位未标定 |
| `/omi/tactile/{a,b}/wrench` | 可选 WrenchStamped，仅匹配 fid 的六维有限值；默认关闭，单位未验证 |

RealSense 可选深度使用官方 `depth/image_rect_raw` 与 camera_info，另可开启
`aligned_depth_to_color`；仅接入参数和录包白名单，未经实机调试。

触觉 QoS reliable/volatile/depth2，状态也为 volatile，以周期发布供录包获取。
触觉同次 snapshot 的所有图像与数值使用同一个主机接收时间，metadata 中可关联；
不同指、RealSense 没有逐帧同步。Wrench getter 没有 fid 或 fid 不符时省略并记录原因。
源 getter 返回非有限值、错误维度、跨帧 fid 时不发布混合帧；累计 dropped 数。
连接/取帧失败重试，5 秒无完整帧触发重连；SDK 内部阻塞仍可能需要 supervisor 强制退出。

## 与旧接口的区别

旧外部 `/tj/dm_sensor/a_raw` 实际由 `getInferImg()` 发布。新实现不复用该误命名：
raw 和 infer 都保留。已有 fixed-baseline CPU 重建发布器用 schema1，与这里的
vendor-flux schema2 不同，不能让两者同时向同一 `/omi/tactile` 前缀发布。
新 metadata 的 baseline 明确未知，不冒充已有离线零载荷 baseline。
旧 dashboard 的显示/固定 ROI 和版本标记未迁移；新采集包可使用 ROS Image 工具看原图，
或由后续消费者基于 schema2 绘制数值场。不要把旧 dashboard 固定版本字符串当成在线算法身份。

## 可复现边界

独立代码、可配置接口、安装入口、版本/哈希记录和无设备验收脚本已提供。
不等于 SDK 可再分发、所有平台二进制兼容、硬件已验收或 apt 依赖被完全锁定。
SDK Python 版本检查是保守声明检查，不是 ABI 验证。Humble 需匹配 Python3.10 的 SDK。
数字场保存后可回放，不承诺从 raw 重建在线 baseline 状态。深度尚未调试。
