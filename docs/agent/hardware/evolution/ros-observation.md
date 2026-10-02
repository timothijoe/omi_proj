# ROS 多模态观测接口

`omi_hil_rl.real` 提供与 ROS 运行时解耦的时间缓存、触觉插入 observation builder、ROS topic 转换层和 Torch 张量适配。默认 topic 对应 `record010`：A 臂关节反馈、夹爪状态、固定与腕部 RGB、双指触觉 raw/depth/force。策略决策时刻只选择不晚于该时刻的最新 header 样本；必要输入缺失或超过默认 0.25 秒会拒绝 observation。

输出包含 22 维关节/夹爪状态、12 维双指力变化、两路 ROI RGB、双指触觉 raw、相对抓取基线的触觉 depth，以及十路传感器年龄和有效标记。头部 RGB 额外保存 ROI 中心相对原图中心的 `[dx,dy]` 像素偏移，允许后续随交互物体移动；Wrist ROI 横向固定居中，不传偏移参数。抓取基线默认取最近 0.5 秒触觉数据的平均值。Torch 适配器添加 batch 维、把 HWC 转为 BCHW，并归一化 `uint8`。

`record010` 的相机预处理尺寸为：头部 `640×480 → ROI 192×192 → 128×128`，Wrist `1920×1080 → ROI 389×389 → 128×128`。两路均先裁正方形再 resize，不引入宽高比拉伸。

工作区同级 `ros2_camera_clip_tools/` 提供离线 rosbag/RViz 检查：第一进程从原图生成两路
128 clip 和原图对照 dashboard，独立第二进程可订阅这两个 clip、最近邻放大到 512 并发布
第二个 dashboard。入口支持只看第一版、只看 512 或双版；另保留最初的单进程第一版入口。
这些 topic 只服务人工可视化，不进入 observation。可视化 clip 使用 Lanczos resize，而
observation builder 当前使用最近邻；ROI 边界一致但像素并不严格一致。操作见
[只读教程](../../../../tutorials/ros_observation_interface.md)。

当前触觉输入只含双指 raw、depth 和各六维 wrench。Daimon SDK 示例还可产生稠密
deformation/shear 向量场并绘制箭头；`record010` 没有这两类字段，新增的
[回放工具](tactile-live.md)可从 raw 重建并发布数值 topic，尚未加入 observation。
逻辑 A 是右侧夹爪 `X26040546`，逻辑 B 是左侧夹爪 `X26040345`；A/B 不是向量方向。
deformation 的每个像素保存相对零载荷基准的 `[dx,dy]` 二维纹理位移，包含接触造成的
面内运动；shear 由厂商 `Decomposer` 从 deformation 派生，厂商示例称其为 `2D curl`，
可作为剪切、旋转和滑移相关特征。由于分解实现加密且单位未标定，当前不能把任一字段
解释为标定后的分布力或切向力。
箭头是人工显示产物，不是合适的策略数据格式；未来若接入，应保存原始有符号
`H×W×2` 数值、使用固定归一化和 CNN 编码。`real.tactile_vectors.render_vector_field`
现已实现人用 renderer：固定网格、scale、deadband 和最大显示长度，不逐帧归一化；约定
图像坐标 `+x` 向右、`+y` 向下，超长箭头使用单独颜色并返回统计。合成方向测试通过，
但尚未完成现场物理方向验收。左右传感器的图像坐标还没有映射
到统一夹爪坐标系，因此 A/B 图中同向箭头目前不能直接解释为同一机器人坐标方向。

离线探针 `real.tactile_offline` 直接加载厂商 `FlowTracker`、`Decomposer` 和
`NormalFromFlowCached`，只读 raw/base，不构造可能打开设备的 `Sensor`。`record010` 的
23、25.5 和 28 秒已实际处理：deformation/shear 均为 `288×384×2 float32`；25.5 秒
松开帧为零或接近零，23/28 秒接触帧产生结构化向量场。接触帧的重建 depth 与记录 depth
空间 Pearson 相关约 0.907–0.951，最小二乘幅值比例约 0.44–0.47，说明空间形状一致但
SDK 默认离线 depth 幅值约为在线记录的两倍。当前只把 deformation/shear 当作候选
数据，不替换 bag 中的记录 depth。本地离线输出已经包含 A/B deformation、A/B shear、
记录 depth 和重建 depth 的 PNG dashboard，以及保存原始矩阵的 NPZ。新增
`tactile_live` 进一步实现带 header 的数值 topic 和独立 raw/向量 dashboard；提供 RViz
配置，完整 depth/wrench 面板与真机在线验收仍待完成。

`omi_hil_rl.real.tactile_baseline` 可从 rosbag 的已知无接触窗口提取双指 raw 时间中位数，
并同时检查夹爪开度、双指 wrench 与 depth。`record010` 的 `25.0–26.0 s` 已通过相机人工
确认持续张开；提取出 A 侧 24 帧、B 侧 23 帧，基准 shape 均为 `270×360 uint8`。夹爪
位置最小值为 1.0，A/B 合力均值约为 0.625/0.472，depth 均值约为
0.00695/0.00637，当前五项 bag 专用启发式检查全部通过。生成物保存在被 Git 忽略的
`local/tactile/`，包含 NPY/NPZ、PNG、相机接触表和 JSON 元数据。bag 不含厂商 serial，
初版 metadata 因此保留空映射。操作者随后确认右侧为 A / `X26040546`、左侧为 B /
`X26040345`，新版 metadata 明确标注该身份来自外部确认而非 bag。Daimon 底层离线重建
本身不依赖 serial。

`ros_bag_preflight` 离线验证 bag；`ros_observation_live` 只创建订阅并打印 observation/Torch shape。两者都不发布控制 topic。当前没有 FK、动作、IK、安全投影、命令插值、奖励、回合或成功判定，不能视为真机环境。形成过程见[相机与触觉核查编年](../chronicles/2026-10-02-camera-roi-and-tactile-review.md)、[离线场重建编年](../chronicles/2026-10-02-tactile-offline-reconstruction.md)和[字段语义澄清编年](../chronicles/2026-10-02-tactile-field-semantics.md)。
