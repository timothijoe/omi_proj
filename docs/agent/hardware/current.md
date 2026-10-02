# Hardware 当前摘要

新外部录包record001已[检查并实现原生字段/末端同屏](evolution/robot-3d-replay.md#新录包原生触觉与末端同屏)：
`view_recorded_observation_3d.sh ZIP_OR_BAG`，domain97，显示原图/128图、原生触觉场、
关节驱动双臂与录包末端三轴。全部21960条解码、Jazzy GUI及循环检查通过，测试120通过5跳过。
**base_link与模型基座关系未经验证，末端与模型约0.93米偏差尚未修复，不能当作正确TCP。**
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
