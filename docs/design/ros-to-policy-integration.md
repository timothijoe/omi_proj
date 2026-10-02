# ROS 到真机策略输入：当前缺口与实施方案

状态：设计方案，不是已完成的在线 RL 接口。2026-10-02 根据当前代码核对。
本方案保留稳定可视化，后续开发走独立入口/版本；不授权设备连接或动作执行。

## 1. 稳定入口与迁移入口分离

稳定入口保持：

```bash
bash scripts/view_observation_bag.sh /home/zhoutong/Downloads/img/record010/bag_001
```

这里的绝对 bag 路径是本机示例，不是代码依赖。稳定 wrapper、调用的 `view_tactile_bag.sh`、
`tactile_live.py` 已恢复到 `d017387` 内容；保留旧外部 SDK 默认路径、原渲染和回放行为。
稳定入口仍可用 `OMI_DAIMON_SDK_ROOT` 显式覆盖 SDK，但本轮不替用户改变默认值。
其专用文件哈希记录在 `manifests/stable-observation-viewer.json`，测试防止误改。
该保护不是完整环境冻结：SDK/venv/ROS、数据文件及共享通用库仍须单独验证。

迁移方案另设入口：

```bash
bash scripts/view_observation_bag_migrated.sh /home/zhoutong/Downloads/img/record010/bag_001
```

对应 `view_tactile_bag_migrated.sh` 和 `tactile_live_migrated.py`，默认使用项目 local SDK，
调用 `omi_sensors.reconstruction`。它仍针对旧 bag 的 infer 图像重建，不是 SDK 原生字段看板。
两个入口使用相同默认domain/topic，不能同时运行；并行比较需要不同domain。
SDK原生看板已另建第三入口 `view_sdk_observation.sh`，默认domain88；
见[当前实现](../agent/hardware/evolution/sdk-native-dashboard.md)，不替换稳定入口。

## 2. 当前真实的数据链

| 环节 | 当前能力 | 尚缺 |
| --- | --- | --- |
| RealSense | 独立包提供官方驱动启动配置，彩色+内参 | 本机驱动未安装/实机未验收 |
| SDK 触觉 | raw/infer/deformation/shear + metadata/status；可选depth/wrench | 实机取数、同fid完整率、标定/基准、SDK兼容性验收 |
| 录包/回放 | 传感器白名单，模拟数据完整链路已验 | 不含新腕部采集、关节/夹爪反馈；不是完整策略数据包 |
| 旧 ROS ingestion | 10路旧topic，Image/Wrench/关节/夹爪转换 | 新SDK topic/元数据/矢量场没接进来；无CameraInfo消费 |
| 旧 observation | 时间选择、过期拒绝、ROI、抓取基准差分、固定shape | depth/wrench/wrist必需；无deformation/shear/TCP |
| Torch转换 | 已有 HWC→BCHW、uint8/255、batch维 | 新字段布局/尺度契约、完整策略checkpoint兼容性未完成 |
| 策略执行 | 有仿真训练/评估；旧ROS节点可返回Tensor字典 | 无新传感器→指定真机策略的只读shadow推理验收 |
| 在线 RL 闭环 | 底层臂SDK边界已有模拟测试 | 动作接口、限幅/停机、episode/reward、训练闭环未整合 |

证据入口：`real/ros_topics.py`、`real/observation.py`、`real/tensor_adapter.py`、
`real/ros_observation_live.py`、`ros2/omi_sensors/omi_sensors/{config,node,tactile}.py`。
旧 `record010` 的269个有效 observation 是旧输入契约的离线证据，不验证新SDK采集链。
能解码32FC2不等于已经订阅并把它放进observation。能得到Tensor字典不等于任意checkpoint能接收。

### 旧接口具体输入

- state：A臂7关节位置、速度、effort和夹爪位置，float32[22]；不是TCP位姿。
- external_rgb/wrist_rgb：各128×128×3uint8；Tensor各为B×3×128×128。
- tactile_raw：双指64×64×2uint8，旧raw实际上来自infer。
- tactile_depth_delta：双指64×64×2float32；wrench_delta：float32[12]。
- sensor_age_s/sensor_valid、头部ROI偏移。

当前 `build()` 仍直接读取腕部、depth、wrench；即使从 required_sensors 列表移除它们，
也不会自动生成不含这些字段的新策略契约。当前采集默认关depth/wrench，因此不能直接喂给旧builder。
CameraInfo通常用于标定与几何预处理，不一定是网络必须输入；没有直接入网不等于传感器不可用。
TCP是否必需取决于具体策略和动作空间，但当前没有对应的TCP观测链，不是唯一缺口。

## 3. 后续统一接口（拟实现）

```text
SDK直读 / 图像重建 / 已录数值场回放
            ↓ 显式来源适配（不自动切换）
统一带元数据触觉样本 + 相机/机器人状态缓冲
            ↓ 时间选择、有效性检查、固定预处理
版本化 observation profile → Tensor适配 → schema匹配的策略
            └→ 新可视化（同一样本，不使用箭头图喂策略）
```

### 3.1 触觉样本

适配 SDK schema2 和重建 schema1 为内部统一样本，保留来源原文；统一 side、serial、fid（可缺）、
source/received时间、timestamp_kind、field_source、input_representation、baseline状态、
算法/SDK哈希、字段单位和坐标、valid/stale/error。未知明确保留，不补造fid/标定。
同指字段按实际fid或可靠source stamp关联；不同指/相机只能按决策时刻选择样本，不假装硬同步。
来源配置/身份在episode中固定；中断就失效/停止推进，不悄悄从SDK切到重建。

### 3.2 版本化策略观测

保留 `legacy_v1` 行为，另建 `sdk_fields_v2`（名字为设计占位，尚无该配置文件/API）。
候选输入如下，最终由训练任务配置和checkpoint声明共同确定，不能运行时随意增删key：

| 字段 | NumPy候选shape | Tensor候选shape | 约定 |
| --- | --- | --- | --- |
| 外部RGB | 128×128×3 | B×3×128×128 | 固定ROI/resize/色序，uint8按固定规则归一化 |
| deformation | 64×64×4 | B×4×64×64 | A_dx,A_dy,B_dx,B_dy，保留正负与SDK原坐标单位 |
| shear（配置可选） | 64×64×4 | B×4×64×64 | 独立字段，与deformation分开 |
| infer/raw（配置可选） | 按选定表示固定 | 固定通道布局 | 不把真正raw和infer混为同一输入 |
| state | 既有22维或显式新版 | B×D | 关节/夹爪反馈必须真实存在、校验单位 |
| TCP（任务选定时） | 明确位置/旋转表示 | B×D_tcp | 明确base/tool frame、单位、FK/反馈来源 |
| age/valid | profile固定顺序 | B×N | 无效样本不得当有效零值进入控制 |

depth/wrench/腕部相机在新profile中可按任务选择，而不是被旧builder强制需要。
相机内参和外参作为可追溯标定；若几何任务需要使用，明确加入预处理或网络契约。
重采样64×64仅改变采样网格时，不暗中按尺寸倍率改变向量的SDK像素单位；若做坐标变换必须显式处理向量分量。
float场用固定统计/尺度，不除255，不逐帧min-max。分辨率和归一化可调整，但必须版本化并匹配训练。

### 3.3 时序与运行边界

统一决策时钟；在线主机接收时间与RealSense驱动时间的偏差/延迟需测量。
bag循环/seek、SDK重连、基准改变触发缓存清理或新episode，防止混入前一段历史。
过期/未来帧、断流、NaN、维度不符、身份改变都必须有拒绝原因。
抓取参考基准与厂商形变零点是不同基准；不能把当前1秒warmup自动采样当作真实抓稳确认。

## 4. 分阶段交付与验收门槛

1. **保护稳定入口（本轮已做）**：专用文件对齐已保存commit，另建迁移版，哈希回归测试。
2. **SDK原生只读看板（实现与合成验收已完成）**：独立入口，RGB+infer/数值场+来源/状态；
   不要求depth/wrench；合成采集、已录字段bag循环播放和断流提示通过。真实接触方向/身份和GUI人工验收待进行。
3. **新版ROS→observation适配**：显式profile、schema1/2来源适配、两类基准、同帧一致性；
   单元测试覆盖旧/新话题映射、缺失字段、时间倒退、重连、过期与单位/方向。
4. **observation→策略契约**：冻结key/shape/dtype/归一化、特征提取器和checkpoint版本；
   离线bag跑完整预处理与网络forward，比较实时/离线同样本的最终Tensor。
5. **真机只读shadow推理**：记录输入、年龄、拒绝原因、推理延迟与候选action，绝不发送action。
   验收FPS、完整率、最差/分位延迟和异常拒绝，门槛按控制频率定义。
6. **在线RL闭环（另行授权）**：动作空间/限幅/急停/看门狗、reset/reward/done、人工接管和经验存储。
   在只读验收和安全验收前，不宣称可在线训练。

其中3—6尚未完成；第2步的真机/GUI验收仍待进行。Humble采集包与主RL包Python>=3.12边界还需解决：
先在匹配Python3.10 SDK的Humble侧验证采集；若训练另进程运行，要明确传输/版本边界，
不能直接混用不同发行版rclpy。Jazzy是当前首个实际验证目标。
