# 2026-10-02：独立 ROS 传感器采集、录包与回放

## 需求和范围

将采集与 ROS 纳入 OMI 自身；外部参考工程不能作为隐式依赖。
用户明确要求 Ubuntu24.04/Jazzy 和 Ubuntu22.04/Humble 两目标；
RealSense 先彩色+内参，深度开发接口但不调试。本轮不连接设备、不发送控制命令。

## 实现

新增独立 `ros2/omi_sensors` ament_python 包、严格设备 JSON、系统安装/构建脚本、
plan/doctor/live/fake/record/replay 入口、Humble/Jazzy 无设备 CI 矩阵。
RealSense 复用官方 ROS 驱动；触觉直接调用 SDK Flux getter，区分 raw/infer/数值场，
检查同 fid 后发布；配置身份、主机接收时间、未知 baseline 都明确标注。
记录限定传感器白名单、版本/源码哈希 manifest 和 topic 数量报告；回放保留旧传感器话题，
禁用的深度不播放，不包含控制命令。压缩源只在临时目录解压。

## 证据

- 本机 Jazzy `colcon build` 成功；安装后从 `/tmp` 可运行 plan，不依赖项目 cwd。
- `scripts/check_sensors_ros.py` 模拟发布→SQLite3 录包→类型/有限性/图像与内参 stamp 校验→回放订阅通过。
- 证据：`local/sensors-smoke-6hjrkgq4/report.json` 与 `session/recording_report.json`。
  14 个 topic；12 路主要数据各176条，A/B status各5条；回放接收176条 deformation。
- 新增契约测试覆盖配置、深度开关、SDK Python 保护、混帧拒绝、数组拷贝、wrench条件、
  不覆盖目录、压缩包源文件不变、回放白名单、Python3.10语法。
- 这些是合成数据与代码层证据，不是相机/触觉设备性能或标定证据。

## 未验收与依赖

本机没有 Humble，也没有安装 realsense2_camera；CI 矩阵已编写但本轮没有远端运行。
未连接 RealSense 或触觉设备；深度未调试。现有厂商包带 Python3.12 加密模块，
Humble 必须另备 Python3.10/目标架构匹配的 SDK。SDK 未复制入仓库。
腕部 gRPC 相机的新采集驱动不在本次范围，旧包回放兼容。
APT 版本有记录但非冻结镜像；厂商 baseline 未知，不保证原图完全复算在线数值。

详见[当前接口](../evolution/sensor-collection.md)与[安装/操作教程](../../../../tutorials/sensor_collection.md)。
