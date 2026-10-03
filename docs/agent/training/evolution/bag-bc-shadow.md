# 录包BC初始策略与ROS影子推理

独立于既有SB3 SAC流程，实现原生触觉录包的BC和ROS消息输入链路验收。
见[设计目标](../../../design/bag-bc-shadow-policy.md)、[教程](../../../../tutorials/bag_bc_shadow.md)。
不连接硬件、不发布实际控制指令，不是已部署机器人控制器。

## 数据和模型契约

`training.bag_bc_data`读取单bag ZIP/完整MCAP目录，每包作为一个episode（成功状态未知）。
10 Hz接收时间网格，选择源header不晚于参考且已接收的观测；任何一路超过250ms拒绝。
输入RGB既有ROI `(3,128,128)`；双指触觉 `(10,16,24)`（每指def2/shear2/depth1，
按18×16块均值降采样）；7关节和双侧12维wrench组成19维状态。不输入命令、夹爪、腕部或eef。
保存各路源时间，时间选择不代表曝光硬同步。动作取参考后100ms起第一条目标，额外等待≤50ms。

必须显式接受左7轴绝对弧度目标假设：JointcmdArm只定义positions，尚未确认生产者语义、
关节映射或实际执行；范围检查不能证明物理语义，不能称为已确认执行动作的真机训练数据。

`training.bc_policy`为小型RGB CNN＋触觉CNN＋状态融合MLP；学习归一化目标残差，
还原加当前关节位置得到绝对目标。无预训练、时序历史、action chunk或在线更新。
统计只用训练episode，保存权重、契约、统计、seed和基线对比。
单包必须显式overfit-smoke，无伪造验证集；正式验证按独立完整episode，内容哈希重复拒绝。
训练NPZ暂整体加载内存，定位小规模试验，不是超大数据训练器。

## ROS影子推理

导出同时生成仅10路观测的MCAP，过滤控制消息。`training.bc_shadow`子进程按原时间
发布原始CDR，主进程实际rclpy订阅、解码，使用共享预处理和每字段128项有界缓冲。
参考消息只带源时间水位、参考点及观测哈希，不含标签。等待跨topic到达的对应源帧，
离线/ROS输入哈希精确一致才推理；缺失/过旧/超时不输出。begin握手清空历史，end等待队列。
默认每轮故意暂停1秒验收STALE；无新参考不重复预测，循环结束正常退出。

默认localhost domain99，拒绝domain0或非localhost配置；只输出shadow命名空间JSON，
没有JointcmdArm/SDK控制输出，域中发现控制topic会失败。预测没有机械限位/碰撞保护，
禁止转发给机器人。只有对照评估阶段读取NPZ标签，标签不进入网络。
参考水位协议是回放验收机制；真传感器自主采样调度、时钟同步与控制安全仍待实现，
不能仅修改domain宣称可上线。

## 当前证据和限制

record001导出108个训练样本，136参考中109观测有效、末尾1个缺未来标签。
500步CPU训练，同段RMSE从0.007524降至0.001781 rad；保持关节基线0.008043。
两次两轮ROS验收各218预测、每轮109，全部输入精确一致；暂停、循环重置、无控制topic通过。
最终模型推理p50/p95/max约0.796/1.005/45.377ms，不是采样到执行延迟。
单段13.55秒过拟合不能证明插孔、泛化、触觉贡献或闭环效果；独立成功示教尚缺。
RGB ROI、动作/时钟语义、触觉身份/基准/单位需现场核实，TCP问题只是绕开而未修复。
Humble、GPU、设备、控制、长期吞吐尚未验收。完整证据见[编年](../chronicles/2026-10-03-bag-bc-shadow.md)。

入口 `scripts/bag_bc.sh {export|train|shadow}`，读取本机viewer.env中的Marvin overlay，
安装项目bc extra及ROS系统依赖，可用OMI_BC_PYTHON、OMI_BC_DOMAIN_ID覆盖。
不需要触觉SDK/机器人mesh；数据/过滤MCAP/权重/报告在Git忽略的local/bc，输出拒绝覆盖。
