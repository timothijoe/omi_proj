# 真机触觉观测、录制与可视化验证需求

## 1. 目标与范围

本需求面向“物体已经夹取，但姿态存在偏差，利用双指触觉完成对准和插入”的真机任务。
目标不是只让策略收到若干 tensor，而是建立一条可审计的数据链：传感器输出可完整录制，
机器输入可确定重放，人可以在同一个 RViz 界面判断数据是否正确、同步且完整。

本阶段只规定只读采集、预处理、录制、回放和可视化。机械臂动作发布、奖励、episode、
在线训练和自动恢复不在本需求范围内。任何验证工具不得发布机器人控制命令。

## 2. 核心验收原则

触觉数据验收必须同时回答两个问题：

1. **数据是对的。** 数值来源、shape、dtype、坐标方向、基线、时间戳和物理响应可解释；
   人工施加已知方向的接触时，图像、向量和六维力呈现一致变化。
2. **数据是全面的。** 传感器和处理后端实际提供的字段必须形成清单；必需字段逐帧可用，
   可选字段即使未接入也要显式报告，不能因没有显示或没有进入网络而被误认为不存在。

“给人看的表示”和“给机器看的表示”允许不同，但必须来自同一带时间戳的数值样本，并能
追溯到同一个传感器、帧号、基线和处理版本。

## 3. 数据需求

### 3.1 每个触觉传感器的字段

双指 A/B 分别维护以下字段：

| 字段 | 目标格式 | 优先级 | 用途 |
| --- | --- | --- | --- |
| raw | `H×W mono8` | 必需 | 原始证据、故障排查和离线重处理 |
| infer/calibrated image | `H×W uint8`，若后端提供 | 建议 | 核对厂商校正或推理图 |
| depth | `H×W float32` | 必需 | 法向形变；机器使用基线差分值 |
| deformation | `H×W×2 float32` | 必需 | 二维表面位移向量，保留 `dx/dy` 正负号 |
| shear | `H×W×2 float32` | 建议 | 剪切/滑动相关向量，需与 deformation 分开命名 |
| wrench | `6×float32` | 必需 | `Fx,Fy,Fz,Mx,My,Mz`；双指合计 12 维 |
| distributed force | 后端实际 shape/dtype | 调查项 | 厂商接口存在但当前契约不明确 |
| contact area | 后端实际 shape/dtype | 调查项 | 接触范围辅助量，当前契约不明确 |

“必需”表示下一版完整触觉 bag 必须录制；“建议”和“调查项”必须在验证报告中说明实际
可用性。不能把 deformation、shear 或 distributed force 统称为“力向量”，文档和 topic
名称必须保持物理含义。

当前术语约定：deformation 是触觉纹理相对基准的二维稠密位移场；shear 是厂商
`Decomposer` 从 deformation 派生的剪切、旋转和滑移相关二维场，厂商示例也称其为
`2D curl`。在厂商算法细节和物理标定没有补齐前，二者都不能解释为标定后的分布力。
A/B 表示传感器身份而非方向：右侧为 A / `X26040546`，左侧为 B / `X26040345`。

### 3.2 每帧元数据

每个字段至少关联：

- ROS source timestamp 和本机 received timestamp；
- A/B 逻辑名称、设备序列号、设备 `fid`（若 SDK 提供）和坐标系名称；
- shape、dtype、单位或“单位尚未标定”的明确状态；
- 处理后端、模型/标定版本或可复核哈希；
- 当前基线的标识、采集时间和采集状态；
- valid、missing、stale、非有限值和设备错误状态。

图像类数据优先使用带 `header` 的 `sensor_msgs/Image`。稠密二维向量场建议使用
`32FC2`；depth 使用 `32FC1`；六维力继续使用 `WrenchStamped`。若实际 ROS 工具链不支持
`32FC2`，替代消息必须仍保留 header、shape、两个有符号通道和明确坐标约定，不能仅发布
画好的箭头 RGB 图。

## 4. 给机器的 observation

机器输入应来自原始数值，不使用人工可视化图片：

- 双指 wrench：基线差分后的 `float32[12]`；
- 双指 depth：统一到 `64×64×2` 的有符号 `float32` delta；
- 双指 deformation：统一到 `64×64×4`，通道为
  `[A_dx,A_dy,B_dx,B_dy]`；
- shear 若启用，同样为双指四通道，并与 deformation 分开保存；
- raw/infer 是否进入策略由后续消融实验决定，但必须可录制和回放。

归一化必须使用固定训练集统计或固定物理范围，保留零点、方向和绝对幅值；禁止逐帧
min-max。向量场以 BCHW 形式进入小型 CNN，由任务损失学习特征；不先绘制箭头，不要求
VAE。若使用翻转增强，水平翻转必须同步反转 `dx`，垂直翻转必须同步反转 `dy`。

第一阶段训练基线仍为 `state + 12D wrench_delta + depth_delta`。只有消融实验显示局部接触、
滑移方向或姿态修正存在不可观测性时，才把 deformation/shear 加入正式策略；录制层不因
暂时未被策略使用而省略这些字段。

## 5. 给人的统一 RViz 验证界面

必须由 OMI 根据收到的数值自行生成一个触觉验证 dashboard，并作为单个 `rgb8` Image
供 RViz 显示。dashboard 至少同时包含：

```text
双指 raw / infer（若有）
双指 depth 原值与 baseline delta 的固定色标热力图
双指 deformation 原始矩阵绘制的箭头图
双指 shear 原始矩阵绘制的箭头图（若有）
双指 Fx/Fy/Fz/Mx/My/Mz 当前值与短时间曲线
各 topic 的频率、样本年龄、valid/stale、fid 和基线状态
处理版本、箭头比例尺、deadband、单位和坐标方向图例
```

人用 dashboard 不进入 replay 或策略 observation。它只消费已经发布的数值 topic；可视化
速度不足时允许丢弃旧帧，但不得改变或阻塞机器观测链。

### 5.1 OMI 自行绘制向量箭头

拿到 `H×W×2` deformation/shear 后，OMI 必须从矩阵生成箭头图，不依赖厂商已经渲染的
图片。实现至少满足：

1. 验证输入为有限的 `float32 H×W×2`；错误 shape 或 NaN/Inf 明确报警。
2. 在固定网格上采样向量；采样步长记录在 dashboard 和验证配置中。
3. 使用跨帧固定的 scale 和 deadband，禁止为每帧自动归一化箭头长度。
4. 保留向量正负方向；标明图像坐标的 `+x/+y` 和传感器物理坐标关系。
5. 颜色或图例表达向量幅值，超出显示范围时明确标记 clipping。
6. 支持黑底箭头和叠加 raw/infer 两种查看方式；两者使用同一数值矩阵。
7. 箭头 renderer 使用合成向量场做单元测试：全零、纯 `+x`、纯 `-y`、径向场和含非有限值
   的错误输入。

箭头图只能证明 renderer 对矩阵的表达是否合理；它不能单独证明 SDK 输出具有正确物理
单位或标定。

## 6. “数据正确”的验证流程

### 6.1 静态和软件验证

- 检查每个 topic 的消息类型、encoding、shape、dtype、header 和频率；
- 用 SDK 同一帧返回值与 ROS 解码值逐元素或按容差对照；
- 检查 A/B、`dx/dy`、力/力矩顺序及坐标方向没有交换；
- 验证基线前后 raw 不被篡改，depth/wrench delta 在基线时接近零；
- 验证录包回放能得到与在线相同的 observation shape 和数值语义；
- 验证所有必需字段缺失、过期或包含非有限值时 observation 被拒绝。

### 6.2 人工触觉场景

在不驱动机械臂的条件下，对每个触觉面分别执行并记录：

1. 无接触静止；
2. 中央法向按压；
3. `+x/-x/+y/-y` 方向轻微切向移动；
4. 不同位置的局部按压；
5. 小幅顺/逆时针扭转；
6. 释放并检查回零、漂移和迟滞。

每个场景同时观察 raw、depth、deformation、shear 和 wrench，记录预期方向与实际结果。
若六维力的单位尚未由厂商标定文件确认，只验证符号、相对变化和可重复性，不把数值写成
N 或 N·m。

## 7. “数据全面”的验证流程

每次录制必须生成机器可读的 inventory/report，至少包含：

- 期望 topic 与实际 topic 的集合差异；
- 每个 topic 的消息总数、有效频率、时间范围和最大/p95 年龄；
- shape、dtype、encoding、非有限值数量和数值范围；
- A/B 的 fid 连续性、丢帧、乱序和时间戳回退；
- 每个 10 Hz 决策时刻选中的源帧及其年龄；
- 必需字段产生的有效/rejected observation 数；
- 可选或调查字段为何缺失，以及是否影响本轮验收。

完整性不等于把所有字段都塞进策略。raw、infer、可视化 dashboard 可以只供审计；机器
observation 可以只选择经实验需要的字段，但原始 bag 和报告必须能够说明哪些数据被选择、
哪些被保留、哪些确实不可用。

## 8. 交付物与验收条件

一次合格的触觉数据验收应留下：

- 包含必需触觉数值 topic 的 MCAP bag；
- topic/shape/dtype/频率/年龄/缺失统计 JSON；
- observation 预检报告和固定时刻的数值样本；
- 统一 RViz dashboard 的截图或短视频；
- 箭头 renderer 的自动测试结果；
- A/B 坐标、基线、单位、模型和标定版本说明；
- 人工触觉场景检查表及异常记录。

验收通过要求：所有必需字段存在；无未解释的 shape、单位或坐标歧义；合成测试和人工方向
测试一致；bag 回放可重复生成机器 observation 与人用 dashboard；验证过程没有发布运动
命令。

## 9. 当前差距

新增的 [实时回放工具](../agent/hardware/evolution/tactile-live.md)已覆盖 raw 重建数值 topic
和独立 raw/deformation/shear dashboard。尚未覆盖本需求中的完整 depth/delta/wrench
面板、人工方向实验、完整录制审计或向量 observation；原始 record010 字段仍保持原状。

`record010` 已包含双指 raw、depth 和 WrenchStamped，但没有 deformation、shear、设备
序列号、SDK fid、处理模型/标定版本和统一触觉 dashboard，因此不满足本需求的完整验收。
bag 的 `25.0–26.0 s` 是已由外部相机人工确认的完全张开窗口；夹爪位置、双指 wrench 和
depth 也同时接近零。OMI 已从该窗口的 A/B raw 分别生成时间中位数基准帧，所以“缺少可用
基准图”不再是离线重处理的阻塞项。Daimon 底层 CPU `FlowTracker` 已验证可以在不提供
serial、不构造 `Sensor` 的情况下从 raw+base 重建 `288×384×2` deformation，随后生成
shear 和 depth。接触时重建 depth 与 bag depth 的空间相关系数约为 0.91–0.95，但默认
离线参数的幅值约为在线记录的两倍，因此不能冒充录制时的在线真值。A/B serial 仍需用于
完整追溯和可能的设备专属 force/标定路径，但不再阻塞 deformation/shear 原型。
操作者随后确认右侧夹爪为逻辑 A、serial `X26040546`，左侧夹爪为逻辑 B、serial
`X26040345`；该映射来自外部人工确认，不是 bag 内生元数据。
