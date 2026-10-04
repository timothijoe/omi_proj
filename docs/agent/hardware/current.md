# Hardware 当前摘要

当前保留[实时 RViz 阶段版本](chronicles/2026-10-04-live-rviz-checkpoint.md)：`bash scripts/view_grid_observation_live.sh`默认domain13，显示双相机/双指三场/EEF及topic状态，默认启用原方向修正版双臂模型。现场Jointfeedback已通过独立消息包修复，关节与EEF轻量订阅约50Hz，15项回归通过。**end effector与模型尚未完全对应**：本次L7—EEF约33.5cm、相对转角120°，基座/TCP关系仍待核对；已用球、坐标轴与连线可视化。保留当前实现，暂不拟合补偿。详细工具说明见[实时看板](evolution/grid-live-review.md)。


最新开关规则：grid默认deformation/shear/depth；raw通过`--publish-raw`、wrench通过
`--tactile-wrench`显式开启。raw沿用`/omi/tactile/{a,b}/raw`，不改变小矩阵场话题。
见[操作教程](../../../tutorials/tactile_grid_transport.md)。可选raw发布已实现，grid回放显示raw尚未适配。

wrench零消息已定位并修复：SDK返回无帧号(1,6)数组，旧适配将其省略；现在保留六维值并
标注未同步。domain13真机本地6秒收到A164/B160条，远端录包待复验。
见[本次证据](chronicles/2026-10-03-wrench-unframed-fix.md)。下述旧包仍缺wrench，不可补回。

当前[触觉24×16数值场传输](evolution/tactile-resolution-and-throughput.md)：
独立启动器`tactile`默认grid并开启depth；wrench显式开启，all/view保留旧full默认。
oct3_011/bag_002已实录并RViz检查：双指三场约28 Hz，depth已显示；wrench仍零消息，
触觉header与录包时钟相差约22 ms，需排查。raw/infer缺失是发布端主动省略，不是订错话题。
可选发布raw已在后续用户授权下实现，之前暂缓记录保留在编年中。
新增通用`view_grid_observation_3d.sh`，已用oct3_022/bag_001验证RViz；
支持ZIP/目录、网格和ROI直显，见[教程](../../../tutorials/grid_bag_review.md)。
旧看板及策略订阅仍未适配；此前local临时预览的检查详情见
[最新编年](chronicles/2026-10-03-grid-bag-review-and-raw-deferred.md)和[教程](../../../tutorials/tactile_grid_transport.md)。

腕部卡顿的完整证据链、无效尝试、有效配置与剩余边界，统一见[视频流性能纪传体](evolution/wrist-stream-performance.md)。

新增[戴蒙触觉/腕部独立实时入口](evolution/sensor-collection.md#独立触觉腕部实时测试入口2026-10-03)：
触觉和腕部相机均已真实出图，RViz同屏首版已跑通；**原默认传输明显卡顿，后续共享内存实验改善了本机订阅连续性**。
原配置腕部发布约30 Hz、订阅约10–12 Hz，见[原卡顿记录](chronicles/2026-10-03-daimon-live-stream-stutter.md)。
后续新增可选 `start_daimon_shm_test.sh`，65秒同机测试达到30 Hz、最长间隔72 ms；
原默认未改，实验已接入当前RViz，用户体感与端到端时延仍待确认。见[传输实验](chronicles/2026-10-03-wrist-shm-trial.md)。
操作见[教程](../../../tutorials/daimon_live.md)，不修改旧回放入口，不控制机器人。

已实现 `--image-mode full|roi` 启动开关，独立128×128 ROI话题与原图话题互斥发布，
RViz/状态显示模式标签；采样与现有策略nearest逐像素测试一致，下游策略与录包接入尚未做。
见[方案与边界](evolution/sensor-collection.md)。

两路裁剪已记录为[ROI第一版约定](../../design/camera-roi-v1.md)：外部(.507,.426,.40)，
腕部(.500,.704,.36)，均裁剪后缩至128；看板与训练插值方式的差异已明确。
**腕部采集问题暂缓**：bag_004画面近乎静止已在源数据中出现，源图/缓存/发布逐级相符；
怀疑采集端但具体原因未定位。时间戳变化不证明有效新画面，见[本次编年](chronicles/2026-10-03-wrist-roi-and-capture-followup.md)。

bag_004新证据：`/tj/dm_camera/camera/color`及CameraInfo已录入，18话题12820消息全解码。
新增[腕部RViz入口](../../../tutorials/wrist_bag_review.md)：domain93，右上腕部原图＋旧版ROI的128预览，
使用中心(.500,.704)/短边比例.36和Lanczos，替换初版中心大方框；右下触觉raw。
直接使用命名修正版模型；ROI对新任务的适用性待观察。
新[EEF v2策略](../training/evolution/eef-action-space.md#v2可选腕部相机与输入源标记)已支持可选腕部，旧七关节BC不变。
下述腕部缺失结论仅针对旧record001，不能套用到bag_004。

当前新增[Stand方向修正版](evolution/robot-3d-replay.md#stand方向修正版2026-10-03)：
左3/4/6、右3/4/5轴按旧回放约定修正，保留新支架高度，独立入口domain94。
派生资源命名`omi_marvin_stand_axis_corrected_v1`，存于项目`local/models/`，不是原版URDF。
134测试通过、5跳过；末端差更符合约23.3厘米工具偏移假设，未做TCP标定。
左joint4限位仍不一致，严禁用于真机控制；见[本阶段编年](chronicles/2026-10-03-stand-axis-correction.md)。

2026-10-03腕部话题议题暂缓：用户指出 `/tj/dm_camera/camera/color`，
当前oct2/record001.zip的metadata未列出该名称；设备端是否发布、是否有另一版本录包待核实。
不推断缺失原因、不继续改代码，详见[议题现状](evolution/robot-3d-replay.md#可视化遗留右上角腕部相机原图与clip待下一次处理)。

**旧record001入口的布局遗留（新bag_004入口已另行实现）**：右上角应显示腕部相机原图与clip，而非触觉预览；
右下角保留A/B raw。新record001包没有腕部图像topic，当前布局不符合这项最终需求。
先取得包含腕部相机的数据，再实现读取与布局；见[纪传体遗留项](evolution/robot-3d-replay.md#可视化遗留右上角腕部相机原图与clip待下一次处理)
与[澄清编年](chronicles/2026-10-02-wrist-viewer-followup.md)。

新外部录包record001已[检查并实现原生字段/末端同屏](evolution/robot-3d-replay.md#新录包原生触觉与末端同屏)：
`view_recorded_observation_3d.sh ZIP_OR_BAG`，domain97，显示原图/128图、原生触觉场、
关节驱动双臂与录包末端三轴。全部21960条解码、Jazzy GUI及循环检查通过，测试120通过5跳过。
**此处旧模型入口仍有约0.93米偏差；新Stand方向修正版已改善高度对应，但base/TCP仍未标定。**
原生/重建触觉幅值差尚未受控比对；触觉约11–12 Hz，时钟语义/动作标签/现场模型仍待核对。
夹爪开合暂不考虑；可先小规模低速示教试采，不宣称训练闭环已完成。见[新阶段编年](chronicles/2026-10-02-native-record-review.md)。

新增[RViz双臂3D录包回放](evolution/robot-3d-replay.md)：
`view_observation_robot_3d_bag.sh`默认localhost domain96，从本地模型生成双臂可视化URDF，
历史关节反馈驱动专用joint_states/TF，模型与视觉触觉看板并排显示。实际RViz mesh和运动已检查。
不回放控制命令；不含现场夹爪/精确TCP，rad、L/R映射与模型尚未经现场标定。

新增[旧包机器人状态同屏入口](../../../tutorials/robot_state_dashboard.md)：
`view_observation_robot_bag.sh`离线读取关节反馈/目标和夹爪状态，追加文字面板。
不回放控制命令、不计算TCP，旧稳定看板文件不变；record010 headless回放、循环及无控制topic已验证。

新增[触觉分辨率与30 Hz吞吐讨论](evolution/tactile-resolution-and-throughput.md)：用户最新倾向
考虑16×24低分辨率数值场；与现有箭头18×24采样网格区分，尚未定案或实施。
完整场/低分辨率发送录包、预训练编码方案留待比较；SQLite3暂保留，缓存只登记观察项。
系统资源检查与载荷算术不构成实机30 Hz无丢帧验收。

[SDK原生数值看板](evolution/sdk-native-dashboard.md)已新增：`view_sdk_observation.sh`，
默认domain88，直接订阅schema2字段，显示彩色/内参、raw/infer/def/shear和有效性状态。
合成数据采集、录包、循环回放、断流STALE已headless验证；旧看板冻结文件不变。
不代表实机SDK或新版RL observation已验收。

图像重建已[迁入独立包](evolution/tactile-reconstruction-migration.md)，新 `_migrated` 看板复用共享适配器，
SDK 运行文件已本地归档且按文件哈希校验。6组历史样本的12个数值场与迁移前逐元素一致；
这不是实机SDK直读等价性验收。重建仍用厂商加密算法，并非自主实现。
原 `view_observation_bag.sh` 链路已恢复d017387专用文件，保持稳定入口。
新SDK数值场到最终策略尚未整合；不只是缺TCP，详见[集成方案及缺口](../../design/ros-to-policy-integration.md)。

新增[独立 ROS 传感器包](evolution/sensor-collection.md)：Jazzy/Humble 目标，
RealSense 彩色+内参、SDK 双指触觉原图/预处理图/数值场、录包与隔离回放。
安装和配置不依赖外部参考工程，也不依赖主 RL Python 环境。本机 Jazzy 构建与合成数据
录包→回放已通过；Humble、真设备和深度尚未验收，Humble 需要匹配 Python3.10 的厂商 SDK。
细节与证据见[采集包编年](chronicles/2026-10-02-sensor-collection.md)。

新增[相机与触觉合并模式](evolution/tactile-live.md#相机与触觉合并模式)：一个播放器、一个
RViz Image，同时显示两路原图/128 ROI 和 A/B raw/deformation/shear。各路保留自己的
时间戳与过期提示，不代表跨传感器逐帧同步。该合并显示阶段自动测试为 59 passed、1 skipped；
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
