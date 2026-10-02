# 2026-10-02：触觉 deformation/shear 字段语义与实现边界

## 目标

在已经完成 rosbag 离线触觉场重建后，明确 dashboard 中 A/B deformation 和 A/B shear
分别表示什么，并记录已实现能力与尚未实现的在线链路，避免把二维位移、剪切派生量和
物理力混为一谈。

## 当时实现

- A/B 身份沿用操作者在 bag 外确认的映射：右侧为 A / `X26040546`，左侧为 B /
  `X26040345`；A/B 不是方向名称。
- `FlowTracker` 先比较当前 raw 与 `25–26 s` 零载荷基准，输出
  `288×384×2 float32` deformation。每个像素的两个通道按 `[dx,dy]` 保存图像平面内的
  触觉纹理位移。
- `Decomposer.decompose(deformation)` 输出同 shape shear。厂商示例把它称为
  `2D curl`；OMI 当前只把它解释为剪切、旋转和滑移相关派生特征，不宣称为切向力。
- OMI 使用固定网格、固定 scale/deadband 和显式 clipping 把数值场画成箭头；箭头 PNG
  只供人工查看，NPZ 中的原始有符号矩阵才是机器处理候选输入。
- 已生成包含 A/B deformation、A/B shear、记录 depth 和重建 depth 的离线 PNG
  dashboard。尚未实现 deformation/shear ROS 数值 topic、独立在线 dashboard publisher
  或 RViz 触觉界面。

## 验证证据

- `record010` 的 23 秒和 28 秒接触帧产生结构化 deformation/shear；25.5 秒松开帧为零或
  接近零。
- 箭头 renderer 已覆盖零场、`+x`、`-y`、截断、错误 shape 和非有限值测试。
- 本轮只整理字段语义与文档，没有修改处理代码，也没有连接设备或运行机器人。

## 当时限制

- deformation/shear 的数值单位没有完成物理标定，箭头长度不能解释为 N。
- 厂商 `Decomposer` 实现经过加密，无法从源码证明其完整数学定义；“剪切/旋转/滑移相关”
  是根据公开接口名称和厂商示例作出的保守描述。
- 当前 renderer 使用图像坐标 `+x` 向右、`+y` 向下；左右传感器图像坐标尚未转换到统一
  夹爪或机器人坐标系，不能直接比较 A/B 箭头的物理方向。
- 当前完成的是 rosbag 离线重建和 PNG 查看，不是 RViz 在线可视化，也没有把向量场加入
  策略 observation。

## 对后续的影响

下一阶段应先发布带 header 的 `32FC2` deformation/shear 数值 topic，再由独立可视化
进程生成 RViz dashboard；同时通过单侧 `±x/±y` 拖动和顺/逆时针扭转标定 A/B 图像坐标
到夹爪坐标的变换。只有消融实验表明 12D wrench 与 depth 不足时，才把原始向量矩阵纳入
正式策略 observation。
