# 2026-10-02：独立 SDK 原生数值看板

## 任务与边界

用户要求实现新SDK原生数值看板，保证旧稳定看板不动，完成后再一起检验。
本轮仅新增独立显示链路及必要安装/测试支持；没有连接硬件、没有修改RL输入或发动作。

## 实现

- 新入口 `scripts/view_sdk_observation.sh`；默认只订阅，显式 `--fake` / `--bag` 启动对应数据源。
- 默认配置domain88，避开稳定看板默认87；输出 `/omi/sdk/dashboard` 与诊断JSON。
- 独立包dashboard模型/解码/渲染、launcher、RViz配置。图像字段与schema2元数据按同stamp配帧，
  有界缓存、不可变核心快照、非法schema/来源/NaN/shape拒绝、接收过期和回放循环识别。
- RealSense原图、128ROI、同stamp/尺寸内参；双指raw/infer/def/shear、数值范围、来源/fid/基准、
  接收频率/年龄及设备状态。depth/wrench可选摘要，不要求它们才能显示。
- 字段直接来自SDK协议topic，不运行SDK、不做图像重建；合成源明确标SYNTHETIC。
- 旧renderer冻结复制到独立包，并做像素等价测试，避免导入主RL包或修改旧renderer。
- 原生bag缺少必要非空topic时启动前拒绝，明确建议record010继续用旧入口。

## 验证证据

- 主项目自动测试108 passed、5 skipped；独立系统Python的采集/看板/稳定入口测试48 passed。
- Jazzy colcon构建通过，Shell语法、git diff空白检查通过。
- 稳定入口及8个专用文件相对d017387无差异，哈希保护测试通过。
- 运行 `scripts/check_sdk_dashboard_ros.py`，证据 `local/sdk-dashboard-check-7qw9k4n0/`：
  WAITING→模拟源/录包→断流STALE→原生格式bag 2倍速循环回放；收到152条看板图像，
  CameraInfo匹配、两指epoch重置、拥有的supervisor退出均通过。
- 保存并查看该目录live.png和stale.png，检查面板、颜色/ROI、原始数值范围、状态标签与箭头布局。
- 另通过 `view_sdk_observation.sh --fake --no-rviz --duration 2` 检查默认domain88及有界退出。
- 验收数据是synthetic，不是SDK真设备；本轮没有交互启动RViz窗口，没有运行Humble环境。

## 后续

用户可先运行 `bash scripts/view_sdk_observation.sh --fake` 检查GUI，再用配置匹配的真实
采集流或SDK原生字段bag验收。旧record010入口仍保留，不可用它代替原生SDK bag验收。
暂无腕部面板、深度热图、wrench曲线；新版ROS→RL observation仍是下一阶段。
本轮未commit、未push。

[当前实现](../evolution/sdk-native-dashboard.md) · [操作教程](../../../../tutorials/sdk_native_dashboard.md)
