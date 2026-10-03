# 腕部相机：采集、ROI/full与查看

配套：[常用命令速查](sensor_commands.md) · [触觉专项](tactile_grid_transport.md)。
三个文件共同维护默认参数、topic和操作约定；旧集成看板与依赖详见[原实时教程](daimon_live.md)。

## 网络采集（示例domain13）

在项目根目录，先检查计划，再启动一种模式。切换前Ctrl+C停止旧camera，触觉可继续运行。

```bash
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network --domain 13 --plan
# 常用：裁剪后128×128
bash scripts/start_daimon_live.sh camera --image-mode roi --transport network --domain 13
# 或：完整1920×1080图像，不与上一条同时运行
bash scripts/start_daimon_live.sh camera --image-mode full --transport network --domain 13
```

| 模式 | topic | 内容 |
| --- | --- | --- |
| roi | `/omi/wrist/color/image_roi` | BGR8，128×128 |
| full | `/omi/wrist/color/image_raw` | BGR8，当前配置1920×1080 |

相机默认full，两个图像topic互斥发布。full是解码后的完整图，不是Bayer RAW。
ROI中心(.500,.704)，边长为短边.36，nearest采样至128；不是去畸变。
原1920×1080对应裁剪左上(766,566)、389×389。ROI包回放只放大，不应再裁一遍。
当前不发布CameraInfo。设备传输仍是MJPG，主机之后的ROS载荷才因ROI变小。

## RViz与同机低延迟选项

另一终端运行，与发布端选择同一模式和domain：

```bash
bash scripts/start_daimon_live.sh view --image-mode roi --transport network --domain 13
```

此view带旧完整触觉看板；若触觉在grid模式，触觉面板不适配，不代表数据没发。
可以只检查腕部图像；当前实时grid触觉显示另待开发。

只在同机查看大图，可停止原camera/view后改用以下配对命令（另两个终端）：

```bash
bash scripts/start_daimon_shm_test.sh camera --image-mode full --domain 13
bash scripts/start_daimon_shm_test.sh view --image-mode full --domain 13
```

共享内存入口限制本机，不能作为远端接收方案；不要与network相机重复启动。

## 接收检查、停止与边界

接收端加载ROS环境并匹配发布端设置：

```bash
source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 topic echo --once --no-arr --qos-reliability best_effort /omi/wrist/color/image_roi
ros2 topic echo --once /omi/wrist/status
```

full模式将图像topic改为image_raw。诊断状态含模式、尺寸、收发计数、耗时与stale状态。
header是主机接收完整JPEG的时间，不是曝光时间；跨机时钟未同步时不能用差值判断网络延迟。
topic存在不等于持续有新图，检查消息计数、帧间隔和画面变化。
遇到camera busy先关闭已知旧会话，不强制断开未知客户端。
Ctrl+C停止camera；关闭独立view不会停止camera。Jazzy本机已验证，Humble/远端组合需现场验收。
