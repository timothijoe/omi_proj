# 2026-10-03：真实触觉接通与腕部实时入口

用户希望分别启动双指触觉与自带腕部相机，用RViz检查时延。

已验证设备网络与两个触觉端口可达；补齐项目venv的 grpcio1.83.0、protobuf7.35.1。
双指SDK报告正常，12秒订阅约330帧/侧，raw640×480、infer360×270，
deformation/shear为288×384×2 float32。存在少量跨fid样本，原适配器拒绝发布。

新增 `start_daimon_live.sh` 及独立腕部协议/采集模块，支持all/tactile/camera/view。
每指独立进程不变；腕部单独进程，使用MJPG/FCP1、有限不完整帧缓存、最新帧覆盖。
默认domain88，与bag回放domain93隔离；只连接传感器，不启动运动和录包。
腕部header为本机完整JPEG接收时间，不是曝光；不将服务端时间直接当作已同步时钟。
当前不发布腕部内参，不纳入通用录包/策略接口。

参考外部camera_proxy.proto与UDP封装，在本项目实现兼容协议；没有运行时外部目录依赖。
自动测试：新增UDP协议测试与原sensor/dashboard测试共45通过、4跳过。
首次腕部真机OpenStream返回RESOURCE_EXHAUSTED，已有session占用；没有强制StopStream对方。
这只证明服务可达且处理请求，不证明当前新客户端成功采到真实相机帧，等待用户释放设备后继续。

长期状态：[独立传感器采集](../evolution/sensor-collection.md)。
操作步骤：[实时启动教程](../../../../tutorials/daimon_live.md)。
