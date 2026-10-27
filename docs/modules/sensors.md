# 相机与触觉采集

职责：采集、发布、记录原始可追溯数值，供策略和人用看板分别消费。独立ROS包 [omi_sensors](../../ros2/omi_sensors) 与训练进程分离，启动采集不等于启动机械臂控制。

## 输入与表示

外部RGB和腕部RGB按profile进行固定ROI预处理，策略两路各128×128。双指触觉采用数值场，当前网格策略输入每帧10×16×24：每指deformation dx/dy、shear dx/dy及depth。具体契约以 [数据接口](../interfaces/data-formats.md) 与checkpoint为准，不用RViz箭头图训练。

触觉A是右侧夹爪、serial X26040546；B是左侧、X26040345，来自原现场人工确认，换设备需重新确认。原始raw、infer、deformation、shear、depth和整体wrench是不同表示；形变/剪切场不能自动解释为标定力，见 [术语](../../CONTEXT.md)。

采集profile决定字段是否提供；某份目标需求列为“必需”不意味着所有配置默认都开。SDK原生采集、旧raw离线重建、已录字段回放保留不同来源，不静默相互替代。SDK、零载荷基准和设备专属标定通常不在Git。

## 采集解耦与时间

grid24x16路径按字段独立读取，某一字段缺失不连带丢弃其他字段。wrench独立调度，不能凭主机时间补造设备帧号或同帧保证。

腕部实时路径保留最新完整JPEG；录制路径有独立有限FIFO及可靠record topic，溢出会计数。实时覆盖、组帧丢失、解码失败和录制队列丢失不是同一种统计，不能简单相加。支持record topic的离线转换优先选择它，不混合重复实时流。

header年龄包含源时间语义与跨机时钟偏差；本机接收年龄只反映回调后经过多久，两者均不等于曝光至决策总时延。外部RGB、腕部和触觉源时钟不可直接视为硬同步。当前在线periodic为latest观测、时序诊断；旧shadow和receipt路径保留不同门槛，不能套用旧接口说明统一推断。

## 验证与待办

10月24日外部RGB本机最后接收为16:32:29.898，17:07:54独立订阅仍无消息，17:08:36.816保存观测已恢复。
该次断流早于V2切换，新旧看板和独立订阅均观察到无发布者。远端网卡掉线是用户报告，未取得远端系统日志独立确认。
**训练latest缓存旧RGB进入经验池已确认**，相机mask仍为1；不能把字段存在或mask当作新鲜度证明。
清理和模型影响见[经验池](replay.md)，门控与事件记录仍为[待实施方案](../design/system-health-monitoring.md)。
V2将过期ROI保留像素并标红STALE只改变观看方式，不改变采集规则。帧率和header年龄需重新现场测量，历史短测不代表当前吞吐。

解耦阶段10秒只读短测三场约30Hz、wrench约29.6Hz、腕部约30Hz，录制metadata有配对证据；不保证长期零丢帧，腕部后续曾见约291ms header age。源时钟、SDK内部推理缓存、物理单位和设备坐标标定仍有边界。

完整验收需已知接触方向、基线、字段清单、丢帧/年龄统计以及可重复重建机器输入；尚未完成的统一要求见 [传感器验收设计](../design/sensor-validation.md)。显示正常不替代输入有效性验证。

操作见 [采集](../../tutorials/sensor_collection.md)、[当前grid命令](../../tutorials/sensor_commands.md)、[采集解耦](../../tutorials/sensor_decoupling.md)、[腕部](../../tutorials/wrist_camera.md)。资源见 [本地依赖](../interfaces/local-resources.md)。

开发历史（按需）：[传感器归档](../archive/sensors/README.md)。
