# 2026-10-03：腕部大图共享内存传输实验

用户授权在保留首版基础上尝试解决长停顿。未更换SDK、未缩小1920×1080原图、未修改系统sysctl。

## 对照与证据

- 原默认普通订阅约11.6 Hz；跳过Python反序列化仍12.2 Hz，队列30仍10.3 Hz。
- 曾记录新订阅socket累计138个UDP数据报丢弃；不能将它等同于138张图像。
- 去掉实验进程旧localhost开关后，XML接收缓冲确实由212992变为8388608字节。
  丢包计数为0仍约9.15 Hz，最大间隔1.10秒：仅增大接收缓冲不足。
- 两端UDP配置加同步发布约10.49 Hz、最大间隔640 ms，仍未解决。
- 两端大图SHM配置（64 MiB segment/8 MiB单消息、loopback UDP及同步发布）：
  初次15秒约30.01 Hz，最大间隔50.15 ms。
- 将相机和RViz切到项目实验入口后，65秒独立订阅1949帧、30.001 Hz，
  间隔p95 45.02 ms/max72.48 ms，无超过200 ms间断；源接收/发布计数约29.99 Hz。
  本机完整JPEG接收至回调年龄中位22.11 ms、p95 26.23 ms、max62.33 ms。
  本窗口畸形帧及latest覆盖计数均未增加，订阅socket未显示丢包。

以上为软件订阅连续性证据，不等于逐帧RViz呈现时间或曝光到屏幕时延验收。
SDK读图/解码、原始图像分辨率没有改变，证据支持先优化ROS大图传输，而非先换SDK。
没有完成逐项参数消融，不声称唯一根因就是某一个缓冲大小。

## 落地与边界

新增 `scripts/start_daimon_shm_test.sh`、`ros2/omi_sensors/config/large_image_shm.xml`，
launcher增加可选 `--transport local-shm`；默认不变。
相机采集、RViz短暂重启；触觉采集始终保留。当前运行实验版本，退出后可用原入口回退。
本机Jazzy验证，仅适用于同机，跨机/Humble未验收，触觉CLI内部环境契约未改。
相关自动测试47通过4跳过，Shell语法与git diff --check通过。没有commit/push。

临时诊断程序 `/tmp/omi_wrist_receive_probe.py`，临时对照配置 `/tmp/omi_probe_udp.xml`、
`/tmp/omi_probe_shm.xml`；正式实验配置已放入项目，不依赖这些临时配置文件。
操作见[教程](../../../../tutorials/daimon_live.md)，当前能力见[纪传体](../evolution/sensor-collection.md)。
