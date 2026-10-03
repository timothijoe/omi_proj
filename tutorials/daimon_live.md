# 戴蒙双指触觉与腕部相机实时预览

常用操作现整理为三个共同维护的入口：[速查](sensor_commands.md)、
[腕部相机专项](wrist_camera.md)、[触觉专项](tactile_grid_transport.md)。
本页保留旧集成看板、依赖与历史实验细节，不作为第四份常用命令主表。

这是新入口，不修改旧 bag 看板。只启动传感器，不发机械臂/夹爪命令，不自动录包。
触觉、相机分别管理；双指触觉组内部仍是一指一个进程，此外还有看板与 RViz 进程，
因此不是操作系统层面恰好两个 PID。

**原默认传输的视频流存在明显卡顿；下述共享内存实验入口已改善本机订阅连续性，端到端时延仍未验收。**
采集端约30 Hz不代表RViz画面达到30 FPS。详细证据见[当前能力与问题](../docs/agent/hardware/evolution/sensor-collection.md)。

## 可选：本机大图共享内存实验

原入口默认传输存在长停顿；另有独立实验入口，不换SDK、不缩小图像。
先停止旧camera和view（分别启动时不必停触觉），再在两个终端执行：

```bash
bash scripts/start_daimon_shm_test.sh camera
bash scripts/start_daimon_shm_test.sh view
```

这等价于原入口加 `--transport local-shm`。相机与RViz使用Fast DDS 64 MiB共享内存段、
8 MiB单消息上限、同步发布和localhost发现；不修改系统sysctl。
配置文件：`ros2/omi_sensors/config/large_image_shm.xml`。
仅适用于同机相机发布/显示，本机Jazzy验证，不能直接当作另一台机器的远程订阅方案。
触觉既有采集/看板CLI内部仍沿用原environment契约，本次不宣称触觉链路完成相同优化。
退出实验后可重新用原 `start_daimon_live.sh camera/view` 回退；不要重复启动。
初次15秒独立订阅实测约30 Hz、最大帧间隔50 ms；并非曝光到显示的延迟验收。
随后RViz并行运行的65秒测试：1949帧、30.00 Hz，最大帧间隔72.48 ms，无超过200 ms间断。
完整JPEG接收至订阅回调的年龄中位数22.11 ms、p95为26.23 ms；不含之前曝光/编码和之后屏幕显示。

## 依赖与检查

### Domain 与跨电脑发现

触觉原始矩阵和小矩阵的区别、完整话题表见[触觉命令对照](tactile_grid_transport.md#原始触觉与小矩阵命令对照)。
跨电脑使用时，停止原触觉进程后，下面两条选择一条运行：

```bash
export ROS_DOMAIN_ID=13
# 原始触觉：每个场288×384×2
bash scripts/start_daimon_live.sh tactile --transport network --tactile-mode full
# 小矩阵触觉：每个场16×24×2（不要与上一条同时运行）
bash scripts/start_daimon_live.sh tactile --tactile-mode grid24x16 --transport network
```

相机、触觉、view 共用域规则：`--domain` > 环境变量 `ROS_DOMAIN_ID` > 默认88。
修改后需要停止并重新启动对应进程。共享内存入口也遵循此规则。

```bash
export ROS_DOMAIN_ID=13
# 同机共享内存相机
bash scripts/start_daimon_shm_test.sh camera --image-mode full
# 同机触觉
bash scripts/start_daimon_live.sh tactile
# 跨电脑触觉（与上面的触觉命令二选一）
bash scripts/start_daimon_live.sh tactile --transport network
# 跨电脑相机：使用普通入口，不能使用限定本机的 shm_test 入口
bash scripts/start_daimon_live.sh camera --image-mode full --transport network
```

network 模式设置 SUBNET 发现、关闭 localhost 限制，并清除继承的
`FASTRTPS_DEFAULT_PROFILES_FILE` / `FASTDDS_DEFAULT_PROFILES_FILE`，使用默认 DDS 配置。
该设置会传递到触觉内部子进程。接收终端同样设置 domain13、`ROS_LOCALHOST_ONLY=0`；
Jazzy端同时设置 `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`。更改后重启节点和ROS CLI daemon。
网络、防火墙、DDS及QoS仍需匹配；没有据此保证Jazzy/Humble互通或全分辨率图像吞吐。
可加 `--plan --pc-host 本机IP` 检查最终环境，不打开设备。

使用 ROS Jazzy（本机）或对应发行版环境；Humble 真机未验收。
默认 Python 为项目 `local/venvs/daimon312/bin/python`，可用 `OMI_SENSOR_PYTHON` 指定
匹配 ROS/Python 的虚拟环境。需要 rclpy、OpenCV、NumPy、Pillow、PyYAML、grpcio、protobuf。
本机 grpcio 1.83.0 / protobuf 7.35.1 已安装在项目虚拟环境，不修改系统 Python。
厂商触觉 SDK 放在 `local/vendor/daimon_tactile`，或传 `--sdk-root`。
腕部 MJPG 客户端由项目实现，不需要拷贝或运行外部 diamond/daimong_ws；不支持 HEVC。

```bash
cd /path/to/omi_proj
bash scripts/start_daimon_live.sh --help
bash scripts/start_daimon_live.sh --plan
```

默认设备 `192.168.14.11`，自动通过路由选择回传的本机 IPv4。
可传 `--host DEVICE_IP --pc-host LOCAL_IP`；设备必须能回传到本机。
未设置环境变量或参数时，默认 localhost ROS domain88，不能与原生模拟源、原生 bag 回放混用。
启动前关闭其他实时采集/厂商预览程序，尤其腕部服务可能只允许一个会话。

## 一条命令启动

```bash
bash scripts/start_daimon_live.sh
```

### 原图/ROI标签开关

共享内存实验入口和原入口都支持 `--image-mode full|roi`，默认 `full`。
一条命令管理全部组件时，采集与显示自动使用相同模式：

```bash
# 请先结束之前启动的采集和看板，避免重复占用
bash scripts/start_daimon_shm_test.sh --image-mode roi
# 改为原图：退出后把 roi 换成 full 再运行
```

如果触觉已经在独立运行，只停止旧camera/view，再分别执行：

```bash
bash scripts/start_daimon_shm_test.sh camera --image-mode roi
bash scripts/start_daimon_shm_test.sh view --image-mode roi
```

| 模式 | 发布话题 | RViz面板标签 |
| --- | --- | --- |
| `full` | `/omi/wrist/color/image_raw` | `Wrist LIVE [FULL original]` |
| `roi` | `/omi/wrist/color/image_roi` | `Wrist LIVE [ROI 128x128]` |

这是启动开关，不是运行时热切换。分终端时camera/view参数必须一致，否则看板等待对应话题。
ROI模式不发布整图，实际ROS负载降为每帧49152字节；相机到本机仍接收完整MJPG。
ROI为既有(.500,.704,.36)，1920×1080下裁剪[766:1155,566:955]，再nearest-rint-linspace至128。
该采样与现有策略实现像素一致，不使用旧人用看板的Lanczos。消息编码BGR8，策略需要RGB时须转换，
且下游不得再次裁剪已裁剪的ROI。此次没有自动修改现有策略订阅源。
状态 `/omi/wrist/status` 包含image_mode、image_topic、原始/输出尺寸、裁剪坐标及处理版本；
标签不烧入图像，RViz按面板大小放大显示。该标签不是逐帧metadata消息，尚未接入录包清单。

启动触觉、腕部与 RViz。默认相机 MJPG 1920×1080，申请30 FPS。
关闭 RViz 或 Ctrl+C 会停止这次启动的进程；相机仅 StopStream 自己取得的 session。
如果任何子进程退出，统一启动也会结束其他进程。不会停止其他机器已有的会话。
本入口用锁防止自身重复启动；不能检测所有外部厂商客户端，不能取代操作前检查。

## 三个终端分别启动（本机推荐复制此处）

每个终端先进入项目根目录：`cd /path/to/omi_proj`。
本机路径为 `/home/zhoutong/omi_folder/omi_proj`；换机器使用实际项目路径。

### 方案A：腕部ROI模式

```bash
# 终端1：双指触觉
bash scripts/start_daimon_live.sh tactile --tactile-mode full

# 终端2：腕部相机，ROI模式（128×128）
bash scripts/start_daimon_shm_test.sh camera --image-mode roi

# 终端3：实时RViz，订阅ROI
bash scripts/start_daimon_shm_test.sh view --image-mode roi
```

### 方案B：腕部全分辨率模式

全分辨率指当前1920×1080完整解码图，不裁剪、不缩放；设备传来仍是MJPG，
不是相机传感器Bayer RAW。方案A/B二选一，不要同时启动两套相机。

```bash
# 终端1：双指触觉（若已运行，不必重启或重复执行）
bash scripts/start_daimon_live.sh tactile --tactile-mode full

# 终端2：腕部相机，全分辨率原图
bash scripts/start_daimon_shm_test.sh camera --image-mode full

# 终端3：实时RViz，订阅全分辨率原图
bash scripts/start_daimon_shm_test.sh view --image-mode full
```

切换模式时：先在终端2、3分别Ctrl+C，保留终端1的触觉，再启动另一方案的终端2、3。
camera与view必须使用相同模式。这里只控制腕部图像模式，不改变触觉分辨率。

如果希望一条命令启动所有组件，先停止以上三个终端，再二选一：

```bash
# 触觉＋腕部ROI＋RViz
bash scripts/start_daimon_shm_test.sh --image-mode roi

# 或：触觉＋腕部全分辨率原图＋RViz
bash scripts/start_daimon_shm_test.sh --image-mode full
```

分别启动时，每个终端各自 Ctrl+C；关闭 view 不会关闭另外两个终端的采集。
`all --no-rviz` 可仅采集，`--duration 15` 用于限时检查。
日志保存在 `local/daimon_live/`，运行时临时配置退出后清理。

## 时延怎么看

- 腕部图像：`/omi/wrist/color/image_raw`，Image/bgr8，BEST_EFFORT、队列1。
- 触觉：`/omi/tactile/{a,b}/{raw,infer,deformation,shear}`，沿用原生采集契约。
- 相机诊断：`/omi/wrist/status`，每秒 JSON，包含帧号、接收/发布数量、覆盖数量、解码/发布耗时及 stale 状态。
- 触觉数值看板15 Hz，只适合观察，不代表触觉采集帧率。测试触觉显示时延时可在 RViz
  另加 Image，直接订阅 `/omi/tactile/a/raw`，队列1、Reliable。
- 相机在后台收UDP，仅保留一个最新完整JPEG，解码时会跳过积压旧帧；最多四个未完成帧，200ms过期。
- `receive_to_publish_ms` 从本机收到完整JPEG起算，包含等待、解码和发布，不含曝光、设备编码、之前网络传输、RViz渲染与屏幕刷新。
- Image header 是本机收到完整JPEG的时间；触觉 header 是本机SDK读取时间。都不是曝光时间。
- 服务端时间只保留为 `server_timestamp_unverified`，没有证明时钟同步，不用它宣称单向网络时延。
- 要量真正“动作到屏幕”的端到端延迟，可用手机高帧率同时拍摄手指在镜头前移动与RViz画面，按帧差估算。仅看 topic Hz 不足以测时延。

```bash
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=88 ROS_LOCALHOST_ONLY=1 ros2 topic echo /omi/wrist/status
```

本版不读取/发布腕部 CameraInfo、不去畸变；可选ROI发布已实现，尚未接入录包白名单或策略输入；
旧 `/tj/dm_camera/camera/color` bag 接口不改。这里只验证实时采集和显示链路。

## 当前验收与故障

- 双指真实SDK采集已验证：12秒约330帧/侧，约27–28 Hz；raw640×480、infer360×270、数值场384×288×2。
- 腕部相机已在原会话释放后成功出图，RViz也确认显示；当前用户观察到明显卡顿，问题未解决。
- 相机发布/接收计数短测约30 Hz，但另一次8秒ROS图像订阅仅100帧（约12.5 Hz），
  需要继续测量发布到显示各环节，不能把发布速率直接当作显示速率。
- 如果返回 `RESOURCE_EXHAUSTED: camera is busy`，先关闭原采集，不强制停止来源不明会话。
- 若看不到窗口，先检查其他屏幕及最小化状态；分终端模式可只重开 `view`，不重启传感器。
  当前布局左侧包含触觉和腕部图像，右侧空白3D区域不是相机画面。
- 自动协议测试覆盖UDP乱序、重复、过期、容量限制与异常数据；这不代替相机真机验收。

## 可选触觉低带宽模式

### 开启触觉 depth 与六维 wrench

当前`tactile`子命令默认grid24x16并开启depth；wrench需要显式`--tactile-wrench`，
raw需要显式`--publish-raw`，详见[命令对照](tactile_grid_transport.md)。默认只需：

```bash
bash scripts/start_daimon_live.sh tactile --transport network
```

默认发布`/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth,metadata,status}`；
wrench/raw需显式开关，infer不发；旧看板尚未适配。`all/view`仍保留full默认，旧三终端看板需显式使用
`tactile --tactile-mode full`。可用`--no-tactile-depth`、`--no-tactile-wrench`单独关闭。

先使用 `--plan` 检查配置，不连接设备：

```bash
bash scripts/start_daimon_live.sh tactile --tactile-mode full --transport network --tactile-depth --tactile-wrench --plan
```

在原触觉采集终端Ctrl+C停止，再启动（不必停止腕部相机）：

```bash
bash scripts/start_daimon_live.sh tactile --tactile-mode full --transport network --tactile-depth --tactile-wrench
```

两指分别发布 `/omi/tactile/a/depth`、`/omi/tactile/b/depth`（Image，32FC1），
以及 `/omi/tactile/a/wrench`、`/omi/tactile/b/wrench`（WrenchStamped，Fx/Fy/Fz/Tx/Ty/Tz）。
SDK力值的标定、坐标系与单位仍需实机确认，不能当作已标定牛顿/牛顿米用于控制。
depth需与其他数值场同帧；wrench接受同帧ID六值或SDK无帧号六向量。
后者标记`unframed_host_read_unsynchronized`，时间仅为主机读取时间，不保证源新鲜度或与数值场同帧。
显式错帧、错误维数、非有限值仍省略；不伪造零值或帧号。录包请同时保留两指metadata/status。
若看板也需要订阅这两项，在view命令中同样加 `--tactile-depth --tactile-wrench`。

在与发布端相同的ROS domain/network环境中检查，不能仅凭topic list存在就认定有数据：

```bash
ros2 topic echo --once --no-arr /omi/tactile/a/depth
ros2 topic echo --once /omi/tactile/a/wrench
ros2 topic echo --once /omi/tactile/a/metadata
```

B指同样检查。开关只影响下一次启动，不会改变正在运行的进程，也不能补回旧包缺失数据。
full模式默认关闭depth/wrench；grid默认开启depth、关闭wrench。wrench适配已做本地真机出流验证；
raw可选发布已做合成ROS检查，尚未做本轮raw组合真机验收。
24×16模式也支持这两个开关：depth区域平均，六维wrench保持原数值，不做空间降采样。

新增独立[24×16数值场发布教程](tactile_grid_transport.md)：
`bash scripts/start_daimon_tactile_grid.sh`。旧全分辨率需显式`--tactile-mode full`；
新模式默认仅发数值场，raw虽可显式开启，但仍不能直接替换本页三终端方案中的完整场触觉源。
