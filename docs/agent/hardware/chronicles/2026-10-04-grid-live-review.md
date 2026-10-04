# 2026-10-04：实时grid观测RViz看板

用户要求参考`view_grid_observation_3d.sh`新增实时topic检查入口。
新增独立脚本`view_grid_observation_live.sh`及`real.grid_live_review`，复用grid绘图，不修改旧回放。
默认domain13网络订阅、2Hz看板，显示双视觉、双指三场、EEF和逐topic频率/年龄/状态；
关节、wrench、raw可选。无SDK会话、bag播放、policy或控制发布。

本机实际相机/触觉出图与RViz界面通过，图像/状态6秒检查收到9/10条；13项测试全部通过。
现场源在不同时间出现/消失，看板显示实时缺失，不把发现topic等同持续收到数据。
EEF一阶段header年龄超过50ms，显示OLD_HEADER，未提高阈值掩盖问题。
首次完整模型显示因缺marvin_description网格失败；短时未发现完整动态TF，改为默认只显示EEF，
完整RobotModel可显式开启，不把其他URDF或零关节假装为现场模型。
最终GUI截图与会话状态在`local/grid_live_review/live_user/`；保留窗口供用户查看。

见[纪传体](../evolution/grid-live-review.md)与[教程](../../../../tutorials/grid_live_review.md)。

## 沿用原模型进行实时排查

用户确认设备整体无大变化，授权沿用原方案。实时看板默认启用归档的
`omi_marvin_stand_axis_corrected_v1`，保留原14维关节反馈顺序/弧度约定，
以独立TF显示模型L7与ROS EEF；base_link与模型根重合仍只是显示假设。
不补零关节，不拟合TCP，缺失或过期反馈有显式冻结提示。
15秒现场检查（`local/grid_live_review/session-en3k_75k/status.json`）中，
相机、腕部、双指三场约27–31Hz；关节与EEF无消息、最终未发现发布者。
这是本次观测，不表示设备永久缺失，末端对齐仍待现场消息恢复后核对。

## 现场消息定义差异定位与修正

关节原始序列化数据可收约50Hz，typed订阅为0；手工反序列化报Fast CDR异常。
现场356字节、本地旧定义572字节。用户提供现场定义：Header与三组
float64[14] positions/velocities/efforts；旧录包定义含arm_*及躯干/头部数组。
新增独立live_feedback_interfaces消息包、实时脚本专用overlay和positions读取；
不修改历史bag接口。新定义实测5秒250条，15项看板/录包回归通过。
该时刻前7关节全零、后7非零，左右映射遵循注释但尚需现场确认。
