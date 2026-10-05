# 2026-10-05：外部RGB时钟与接收年龄排查

本记录承接[采集解耦开发与实测](2026-10-05-sensor-decoupling.md)。功能级结论见[时间基准纪传体](../evolution/sensor-time-alignment.md)，实现方法见[采集解耦纪传体](../evolution/sensor-decoupling.md)。

## 1. 解耦后确认“哪个RGB延迟高”

本次指外部 `/camera/camera/color/image_raw`，不是腕部ROI。`local/sensor-decoupling-20261005/zero-preview/report.json` 中外部RGB122帧，header age中位392.2510 ms、p95 443.0622 ms、最大497.9436 ms；腕部record261帧，中位10.8088 ms、最大14.8401 ms。strict窗口0，外部RGB被拒122次。

两路header起点不同，不能据此断言外部相机比腕部曝光到接收慢约381 ms。诊断零动作样本不是正式训练验收。

## 2. 后续8秒只读探针

外部RGB收到160帧，header age中位250.9318 ms、p95 269.3555 ms、最大342.1984 ms；header间隔中位33.3596 ms、最大433.5642 ms。腕部收到233帧，年龄中位13.1729 ms、最大290.9031 ms，header最大间隔110.8209 ms。

这组数据来自本轮会话终端探针输出，未另存逐帧原始日志。不同窗口数值有变化；不能减去固定392 ms当作完成校准，也不能保证腕部永不积压。

## 3. 检查时钟与相机参数

用户怀疑外部相机时间基准不同。只读参数查询得到：颜色配置640×480×30、`rgb_camera.global_time_enabled=true`、自动曝光开启、`auto_exposure_priority=false`、`frames_queue_size=16`；`enable_sync=false`、`use_sim_time=false`。未修改参数，未确认源主机时钟和完整启动命令。

本机 `timedatectl` 在当日22:50左右报告 `NTPSynchronized=yes`；只说明本机状态。GLOBAL_TIME映射至相机连接主机的系统时间，不是跨机器同步保证。发现RealSense metadata topic，但本机缺对应消息包，未解码其中的设备时间。

旧四包审计 `local/four-demo-audit-20261005/verified-controller-schema/summary.json` 中，第二包最小header age为−76.3257 ms、第四包为−13.4443 ms，提示时间基准/语义存在疑点；不能据此证明当前正年龄全部来自时钟偏移。

## 4. 澄清网络输入检查并记录后续方向

入口header检查和采样时本机接收年龄检查同时存在；当前手柄策略wrapper将外部RGB两项上限分别设为500 ms，没有跳过header检查，也没有时钟校正。

用户提出看两种年龄差，差大则认为没问题。讨论后的记录原则：接收新鲜可以单独描述，源时间不确定必须保留；较大差值无法区分时钟偏差与真实积压。外部RGB专用接收时间策略是后续方案，**尚未开发**，全局诊断模式不能替代正式发布模式。

本轮进展归档同时补齐采集解耦实现纪传体、当前摘要、索引与教程。文档更新不代表重新运行采集测试；90项通过与现场频率数据属于此前实现阶段验证。
