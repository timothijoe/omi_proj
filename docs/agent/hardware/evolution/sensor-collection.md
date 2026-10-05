# 独立传感器采集与回放

## 2026-10-05 当前实现

真实grid触觉已改为逐字段独立读取、校验和发布，六维力优先单独调度；腕部默认增加有限JPEG FIFO、可靠record输出和最新已解码实时输出。实现文件、线程/进程关系、元数据、离线转换及剩余阻塞边界统一见[采集解耦纪传体](sensor-decoupling.md)，操作见[教程](../../../../tutorials/sensor_decoupling.md)。下方2026-10-03各节保留当时阶段事实，其中“仅最新JPEG”“未整合录包”等限制已有上述后续更新。

腕部长停顿的排查与解决过程集中维护于[视频流性能纪传体](wrist-stream-performance.md)，本页侧重采集能力和接口。

实现：`ros2/omi_sensors/omi_sensors/`。独立 ament_python 包，Python >=3.10；
主 RL 包 Python >=3.12 的要求不变。安装/用法见[教程](../../../../tutorials/sensor_collection.md)。

## 职责

- `config.py`：严格 schema、设备配置、RealSense launch 参数、传感器 topic 白名单。
- `tactile.py`：厂商SDK连接与旧匹配帧路径；真实grid独立读取现由 `independent_tactile.py` 实现。
- `node.py`：每指独立进程与路径分派；旧路径保留同帧header，真实grid使用字段自身读取结束时间及schema4元数据。
- `cli.py`：plan/doctor/live/fake/record/replay；子进程组退出管理、录包版本/数量报告、私有解压。
- `reconstruction.py`：从原看板迁入的固定基准 CPU 图像重建；`vendor_bundle` 与 `reconstruction_check` 提供归档/回归工具。
  见[迁移方案](tactile-reconstruction-migration.md)。

不调用参考工程、不启动控制节点、不发布动作。通用cli live暂不包含腕部 gRPC 相机；
旧腕部相机 bag 保持允许回放。完整策略 observation 所需关节/夹爪反馈仍由已有只读接口提供。

## 独立触觉＋腕部实时测试入口（2026-10-03）

`scripts/start_daimon_live.sh [all|tactile|camera|view]` 独立管理采集与RViz，默认domain88。
使用 `live_launcher.py`、`wrist_live.py`、`wrist_wire.py`；旧cli、回放与看板布局不改。
腕部协议根据外部参考的 camera_proxy.proto / FCP1 编写，运行时不导入外部工程。
相机只保留最新JPEG、队列1 BEST_EFFORT发布 `/omi/wrist/color/image_raw`；
本机完整JPEG接收时间不是曝光时间，未实现相机内参发布和录包白名单整合。
统一启动遇子进程退出时清理本次启动的其他进程；分终端运行则分别停止。
详见[操作与时延边界](../../../../tutorials/daimon_live.md)。

真触觉已接通，12秒约330帧/侧；原始图640×480与预处理图360×270分开发布。
少量getter fid不一致样本被主动丢弃，不伪造同步。SDK gRPC依赖已在本地venv补齐。
腕部已有会话由用户协调关闭后，新客户端成功启动MJPG 1920×1080、申请30 FPS；
真实Image订阅与RViz画面均已确认。启动受阻历史见[首阶段编年](../chronicles/2026-10-03-daimon-live.md)。

**原默认首版可出图，但视频流存在明显卡顿；新增共享内存实验配置改善了同机订阅连续性，见下文。**
用户现场体验优先于进程存活、streaming标志和发布计数，不能将这些指标当作性能验收。

- 状态计数短测：完整JPEG接收及Image发布均约29.99 Hz。
- 另一次8秒独立ROS图像订阅：100帧，按首尾接收间隔估计约12.53 Hz。
  两次测量不在同一窗口；提示需要分段定位，不能据此精确计算丢帧率或认定DDS就是根因。
- 完整JPEG本机接收到发布抽样约12–15 ms，不含曝光、编码、之前传输及屏幕呈现，不是端到端时延。
- 曾出现累计malformed=1，且latest覆盖计数为0；这是短时观测，不代表无UDP丢包或其他环节无积压。
- 触觉看板固定15 Hz；RViz自己的渲染FPS也不等于相机新帧率。
- 窗口曾位于另一屏/隐藏，重开view后主屏确认腕部与触觉画面；此问题与视频卡顿分开处理。
- 当前未发布腕部CameraInfo、未做同步标定，也未整合相机到通用录包白名单和策略输入。

下一步先在同一时间窗口分段测量：完整JPEG接收→解码→ROS发布→订阅→屏幕；
对照相机单独运行、触觉同时运行、看板关闭/开启，记录帧号、间隔分布、CPU/内存与数据量。
再决定是否调整图像传输格式、显示分辨率、QoS或绘图频率；这些均是待验证方案，尚未实施。
真实动作到屏幕的时延需要另外测量，保留原图与数值场语义，不为显示顺滑伪造新帧。
后续事实见[出图与卡顿编年](../chronicles/2026-10-03-daimon-live-stream-stutter.md)。

### 可选本机大图传输实验

`start_daimon_shm_test.sh camera/view` 为独立实验入口；原启动脚本的默认行为不变。
使用 `large_image_shm.xml`（64 MiB segment、8 MiB maxMessageSize、loopback UDP）、
同步发布，移除实验子进程的旧ROS_LOCALHOST_ONLY开关，使用LOCALHOST发现。
不修改系统网络参数、SDK、相机分辨率及topic。不声称适用于跨机器传输或Humble。

实测仅增大UDP接收缓冲至8 MiB虽然消除了测试socket丢包，却仍约9–12 Hz；
两端UDP配置加同步发布也仍约10.5 Hz。大图共享内存组合配置后，RViz同时运行的65秒
独立订阅收到1949帧，30.001 Hz，最长帧间隔72.48 ms，无超过200 ms间断。
消息年龄中位22.11/p95 26.23/max62.33 ms，起点是完整JPEG本机接收，不是曝光。
说明大图ROS传输配置是有效改善方向；尚未逐个消融SHM段大小/传输选择/发布模式，不能归因于单一参数。
触觉采集未重启，其既有CLI的环境设置不变；本轮不宣称触觉传输优化完成。
相关测试47通过4跳过；[实验编年](../chronicles/2026-10-03-wrist-shm-trial.md)。

### 下一步：独立策略ROI话题（发布开关已实现，下游接入待做）

用户确认在保留共享内存传输改善的基础上增加策略ROI发布，不直接取消整图能力。
当前腕部在线发布器增加 `--image-mode full|roi`，默认full。
full发布 `/omi/wrist/color/image_raw`；roi发布 `/omi/wrist/color/image_roi`，只创建所选Image发布器。
128×128 BGR8 ROI采用与现有策略一致的nearest-rint-linspace，几何参数(.500,.704,.36)。
RViz运行配置按所选模式生成，面板明确FULL/ROI，状态包含模式、尺寸、边界、处理版本。
启动时选择模式，切换需重启camera/view；原始像素不叠加文字，不自动接入策略/录包。

- 在线策略拟优先使用裁剪后缩放的128×128图像；下游须识别已裁剪图，避免二次裁剪，并按BGR8编码转换RGB。
- 沿用[ROI第一版几何](../../../design/camera-roi-v1.md)作为起点，训练与推理必须统一ROI、插值、颜色顺序和版本。
  新在线ROI采用现有策略nearest，与旧人用看板Lanczos仍有区别，不声称所有旧入口插值已统一。
- RViz在订阅端放大，不为显示成512像素而发送512×512版本。
- 保留整图发布/录制的可选能力；初期示教建议存整图便于重新裁剪，不能在ROI未稳定时直接丢弃视野外数据。
- 若裁剪发生在本机解码后，降低的是本机ROS发布、订阅、写盘负载，不降低设备到本机的MJPG网络负载。
  设备侧ROI编码发送是否支持尚未验证，不作为既有能力。

按8位三通道、30 Hz计算未压缩像素负载（十进制MB，不含协议/复制开销）：

| 发布尺寸（宽×高） | 每帧 | 每秒 | 相对1920×1080 |
| --- | ---: | ---: | ---: |
| 1920×1080整图 | 6.2208 MB | 186.624 MB | 1 |
| 389×389裁剪、未缩放 | 0.453963 MB | 13.61889 MB | 约缩小13.7倍 |
| 裁剪后128×128 | 0.049152 MB | 1.47456 MB | 约缩小126.6倍 |

负载比例不等于CPU用量或端到端时延也按同比下降；两者需要实测。
本机实验不解释其他机器录制的旧bag异常：bag录制也经过ROS订阅，但此前bag_004源画面近乎静止、
oct3_009原消息间隔及本机显示停顿必须分开诊断，不能统一归因于同一个DDS参数。
讨论记录见[编年](../chronicles/2026-10-03-roi-stream-plan.md)。

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
数字场保存后可回放，不承诺从 raw 重建在线 baseline 状态。触觉网格depth已在最新实录包中显示，
不等于深度标定或RealSense深度链路验收。
## 可选触觉24×16数值场传输

触觉实时启动器已提供`--tactile-depth --tactile-wrench`及对应`--no-`开关；
`tactile`默认grid24x16并开启depth，wrench需显式开启；显式full以及all/view默认仍关闭；
full/grid模式均可显式启用，view也可启用对应订阅。沿用SDK同帧检查，
无效或显式错帧wrench不发布；SDK无帧号六向量现已适配，标记未同步而非丢弃。
metadata的wrench_provenance说明无SDK帧号、主机读取时间、新鲜度/单位/轴尚未验证。
真机本地6秒接收A164/B160条wrench；远端录包仍需复验，历史空包不可补回。
见[修复证据](../chronicles/2026-10-03-wrench-unframed-fix.md)。
见[开启教程](../../../../tutorials/daimon_live.md)及
[编年](../chronicles/2026-10-03-tactile-depth-wrench-flags.md)。

### 原始与小矩阵入口对照

从项目根目录执行；先停止旧触觉进程，再选择一种模式：

```bash
export ROS_DOMAIN_ID=13
# 原始完整场
bash scripts/start_daimon_live.sh tactile --transport network --tactile-mode full
# 小矩阵场：与上一条二选一
bash scripts/start_daimon_live.sh tactile --tactile-mode grid24x16 --transport network
```

原始每场288×384×2，小矩阵每场16×24×2；两者均为float32双通道、
`sensor_msgs/msg/Image`的`32FC2`编码。原始话题为
`/omi/tactile/{a,b}/{deformation,shear}`，小矩阵为
`/omi/tactile_grid24x16/{a,b}/{deformation,shear}`，花括号表示各指/各场的独立话题。
小矩阵采用18行×16列区域平均，单场数值载荷由884736降为3072字节。
处理位于主机SDK之后，不减少设备到主机的SDK流量。

域选择遵循 `--domain` > `ROS_DOMAIN_ID` > 默认88。
network模式允许子网发现并传递到触觉内部进程；不传则仅本机。
这不代表已验证Humble跨版本接收或远端持续帧率。
详细检查命令、恢复和录包见[触觉教程](../../../../tutorials/tactile_grid_transport.md)。

`bash scripts/start_daimon_tactile_grid.sh`在SDK快照后将deformation/shear区域平均为高16宽24，
通过独立`/omi/tactile_grid24x16/{a,b}/...`发布；旧看板使用显式full采集，all/view默认不变。
低带宽模式默认不发送raw/infer，raw可显式开启；尚未接旧看板、策略和原录包白名单。
只减少ROS流量，不减少设备→SDK流量。Jazzy合成验证及oct3_011/bag_002实录回放通过，
长期持续采集、时钟同步与wrench仍未验收。
详见[分辨率与吞吐纪传体](tactile-resolution-and-throughput.md)及
[操作教程](../../../../tutorials/tactile_grid_transport.md)。

### raw显式发布与教程维护

操作文档三件套：[常用命令](../../../../tutorials/sensor_commands.md)、
[腕部相机](../../../../tutorials/wrist_camera.md)、[触觉](../../../../tutorials/tactile_grid_transport.md)。
三者互链，参数默认/话题/常用入口变更必须同步核对；旧daimon_live保留集成看板和详细依赖。

grid默认在`node.py`跳过raw/infer publisher，`--publish-raw`显式恢复原话题raw发布；infer仍省略。
因此默认`tactile --transport network`没有raw消息，不是接收端名称配错；
SDK内部仍读取原图，不能把ROS省略误认为传感器没有图像。
full模式仍为`/omi/tactile/{a,b}/raw`，未改名。
后续用户授权后，`--publish-raw`已实现：grid模式额外发送SDK原尺寸raw，
沿用`/omi/tactile/{a,b}/raw`，与数值场同快照发布，不独立限帧；infer仍省略。
wrench同时改为显式`--tactile-wrench`才开启。旧full保留原图默认，通用grid回放raw显示待适配。
最新包证据与预览边界见[编年](../chronicles/2026-10-03-grid-bag-review-and-raw-deferred.md)。
