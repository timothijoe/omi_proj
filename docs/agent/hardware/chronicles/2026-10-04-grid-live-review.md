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

## EEF刷新卡顿排查与分进程修复

EEF轻量订阅约48.6Hz，原10Hz看板订阅/三维更新仅约6.7Hz，渲染进程约占一个CPU核。
将关节/EEF订阅及三维更新移入独立进程，默认30Hz；图像看板默认2Hz，RViz上限30Hz。
15项回归通过。实测5秒源48.2Hz，TF与markers约29.2Hz；仍出现一次约0.33–0.35秒接收间隔，
不能宣称完全消除所有卡顿。模型进程统计源约50Hz，EEF源header一度超前约109ms。
未加任何坐标补偿；此时L7—EEF距离约33.6cm、转角约90度。
证据：`local/grid_live_review/session-ecwim0v3/refresh_check.json`、`model_status.json`及`screen.png`。

## 用户授权临时基座平移补偿

以当前播放的oct3_022/bag_001为基准，实时corrected模式显示默认加
[-62.159,-171.229,+0.024]mm；仅变换显示位置，保留灰色原始EEF，四元数不变。
原topic、影子模型输入和回放入口不改。可用--eef-offset-base-m 0 0 0恢复无补偿显示。
固定偏移源自单姿态对照，未当作标定。显示中新增对回放局部关系的残差。
16项显示/回放回归通过，覆盖原始数组不变、姿态不变和零偏移恢复。

补偿后实际标记检查：L7—EEF约23.3cm、姿态相对角90度，相对回放局部关系位置残差约2.14mm。
这是当前姿态的观测，不能保证其它姿态残差相同；原始和补偿后位姿及检查保存在
`local/grid_live_review/session-8kr8vxxh/offset_check.json`，截图为同目录screen.png。
