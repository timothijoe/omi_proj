# 实时小矩阵观测看板

2026-10-04新增`view_grid_observation_live.sh`，参考录包grid viewer的绘图布局，独立实现实时监测。
使用`grid_live_review.py`，复用grid decoder/renderer；原回放文件没有修改。
默认domain13、SUBNET、2Hz看板刷新；订阅直接来自现有ROS发布者，不打开SDK、不回放命令。
操作见[教程](../../../../tutorials/grid_live_review.md)。

输入为外部RGB、腕部ROI128、双指deformation/shear/depth、左臂EEF；关节、wrench、raw可选。
每路保留最新合法样本及最多150个接收时刻，统计近期3秒Hz，显示接收/header年龄、发布者及状态。
异常样本清除旧值，过期/时钟异常图像不继续显示；收到数据与形状合法、同步、标定分别说明。
EEF50ms、其他250ms、header超前100ms提示阈值沿用在线契约。

当前默认沿用原方向修正版Stand模型，以/omi/live_grid/model命名空间发布显示专用joint_states、TF与robot_description，另有model_markers。
不发布运动命令或现场全局joint_states/TF。三维显示分别标注L7与ROS EEF，基座重合仍为原显示假设，不是标定结论。
原现场Pose/RobotModel模式可通过--model-mode none/existing选择，--robot-model等同existing。
大图DDS配置保留网络UDP发现和64MiB SHM，仅影响新子进程。

## 已验证

最初基础回归11通过、2因CPU测试环境缺yaml跳过；补齐系统yaml搜索路径后13项全部通过；缺失/过期/异常/时钟状态及旧布局回归覆盖。
实际domain13约12秒：RealSense原图、腕部ROI和双指三场均出图；EEF约50Hz，
一部分采样header年龄超过50ms，正确显示OLD_HEADER。关节发布者可见但未收到数据，
wrench/raw无发布者；这些均作为可选显示，不伪装为有效零测量。
实际RViz窗口显示相机/触觉及实时状态，首次RobotModel因缺mesh报错，改为默认关闭。
可视化输出订阅、无控制发布检查及最终GUI记录见local/grid_live_review/。

这是人工检查工具，不是策略在线节点、同步验收或机器人坐标标定。

最终RViz默认配置已实际打开，缺mesh报错消失，图像/状态输出6秒检查收到9张dashboard与10条status。
运行期间不同时间RealSense/EEF发布者出现或消失，表格相应变化，不固定宣称现场源始终齐全。
初次GUI定时结束遇到Jazzy上下文关闭时take_message异常，增加仅在上下文已关闭时的退出处理。
最终截图`local/grid_live_review/live_user/screen.png`；只生成看板输出和标准ROS日志/参数事件。

## 用户确认沿用原设备方案后的更新

默认模型改为归档 `omi_marvin_stand_axis_corrected_v1`，本机网格齐全。
保持原回放的14维joint_feedback映射及弧度约定，不额外翻轴、不拟合TCP。
缺少反馈时不补零；已显示过的模型可能保留最后姿态，并标明FROZEN。
新增过期、frame不符与时钟偏差显示规则测试；14项回归通过，ROS消息构造新鲜/过期分支通过。
现场15秒检查相机/触觉27–31Hz，关节和EEF无消息；实时RViz已启动并加载模型描述，
但当前姿态与末端对齐尚无法确认。此结果与此前EEF50Hz属于不同时间段的观测。

## 实时关节接口修复

用户提供的现场Jointfeedback仅含Header与positions/velocities/efforts三组14维数组。
旧bag消息包含arm_*及躯干/头部字段，导致现场原始数据可达但反序列化失败。
现用独立 `ros2/live_feedback_interfaces/marvin_msgs` 编译到 `local/live_feedback_ws`，
实时脚本单独加载，旧bag路径不改。新接口验证约50Hz，15项回归通过。
原左7/右7映射不变；现场前7全零的有效性、左右臂语义仍需核对。
