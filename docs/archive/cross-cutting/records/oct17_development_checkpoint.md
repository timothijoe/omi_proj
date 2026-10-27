> 历史资料：原路径 `docs/oct17_development_checkpoint.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../current.md)；本页保留原过程与证据。

# 2026-10-17 开发快照：SpacePilot、AprilTag 与控制响应

本页是19:51提交521fd47附近的早期阶段快照。后续采集接入、按键定制、速度对齐、CUDA BC及在线RL见[全天编年](../../online-rl/records/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)与[当前纪传](../../online-rl/records/training/evolution/spacepilot-bc-online-rl.md)；下文“先固化/未接训练”类边界只代表当时状态。

本页汇总当前工作区的实现、操作入口、现场证据和待办，供本次本地提交及后续继续开发使用。**当前先固化基线，不提高速度、刚度或更改停止策略；优先补齐SDK提交、目标和反馈测量。**

## 1. 当前功能与文件

| 范围 | 入口/模块 | 验证与限制 |
| --- | --- | --- |
| SpacePilot 六自由度演示 | `hardware/spacepilot_pose.py`、`scripts/spacepilot_pose.sh` | 驱动、GUI、位姿导出及测试；演示本身不发布机器人动作 |
| SpacePilot 末端控制 | `real/spacepilot_control.py`、`scripts/spacepilot_test.py` | 手动话题、SDK换轴、独立倍率、实体3启用；用户已试用，仍有起停拖尾 |
| 输入诊断 | `scripts/spacepilot_input_check.py` | 只读输入/按键/候选记录，不连接ROS |
| 控制响应记录 | `scripts/record_control_response.sh`、同名Python | 非零指令触发，记录指令/关节/EEF/回执/告警；不发布动作 |
| 离线分析 | `scripts/analyze_control_response.py` | 生成阈值分析和曲线；不连接ROS或SDK |
| AprilTag 估计与跟随 | `ros2/marker_detect/tag_pose.py`、`tag_follow_tag_v2.py`、`real/tag_follow*.py` | 原文件已迁入，后续实现ROS图像、X/Z标定、按键与独立/训练内跟随，见[专题](../../marker/records/marker_detect.md) |
| tag10 手眼标定 | `tag_handeye_calibration.py`、`real/tag_handeye.py` | 本机原始样本、结果与质量检查保留；内部残差不是独立精度验收 |
| 异步RL标签跟随 | `hil/async_training.py`、`alternating.py`、`ros_transport.py`、`periodic_control.py`、`periodic_replay.py` | LB组合键、回合暂停、候选失效、control_epoch隔离；不把跟随位移当作RL transition |
| Ubuntu 22.04依赖说明 | `tutorials/ubuntu2204_online_rl_dependencies.md` | 明确Humble/Python ABI与项目Python>=3.12约束，非跨机实测验收 |

手柄读取器还包含“先清空fd所有权，再关闭”的退出修正。上述包括工作区同期功能；其他主题的现场证据以各自文档为准，不冒充本次时延排查的新验收。

当前小型标定结果 `ros2/marker_detect/handeye_result.json`、两轮原始样本及剔除第15条的派生样本/验证JSON一并作为本机实验快照保存。它们依赖当时相机、tag10安装和TCP，不能直接当作换设备后的通用标定。独立跟随/异步RL使用时应显式指定正确的标定路径。

## 2. SpacePilot 约定

- 前+X、左+Y、上+Z；设备原始平移 `[x,y,z]→[z,-x,y]`，角速度 `[rx,ry,rz]→[rz,-rx,ry]`，包含roll方向修正。
- 内部为米/弧度名义周期增量。SDK出口做 `(x,y,z)→(x,-z,y)`，旋转向量转ABC；与手柄共用转换函数。
- 当前实体3上报ID19，机器人入口默认 `--enable-button 19`，按住启用、松开归零。GUI旧模式键ID12/13/14属于另一入口的历史映射。
- `--mode translation|rotation|all` 选择轴组；`--dominant-axis` 只留最强一轴，有1.35倍切换滞回。六轴同时响应需去掉该开关。
- 默认10 Hz，基础速度10 mm/s与10°/s。平移上限=`speed-mm-s × scale × translation-scale`；旋转同理用 `rotation-deg-s × scale × rotation-scale`。各组三轴按范数限幅，倍率0禁用该组。
- 用户提及350 mm/s对19.38°/s的比例，未直接设为真机默认。保持平移10 mm/s时，对应旋转约0.554°/s，即独立倍率1与0.05537；现场另试过1与0.054、1.5与0.1/0.3，不能混称同一实验配置。
- 首条有效非零动作立即发送，持续运动10 Hz；全零也立即发送，再次起动不等旧周期。这里的立即是本轮检测到输入后发送，不是物理零延迟。
- 输入过期150 ms归零；断连、设备变更及循环停顿超过250 ms撤销启用。退出尽力发零。此入口未绑定夹爪、回位或RL数据录制。

用户三方向预览确认：前推→SDK +dx、左推→+dz、上提→-dy。all模式会同时接受旋转，不能将混合输入作为纯平移验收。

## 3. 操作与网络

完整步骤见[SpacePilot教程](../../../../tutorials/spacepilot_control.md)。domain应为13，发现范围按部署匹配。早期LOCALHOST不可见而SUBNET可见；后续本机接收端两种探测均可见，不将早期现象当作固定拓扑。

```bash
cd /home/zhoutong/omi_folder/omi_proj
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export ROS_DOMAIN_ID=13 ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET

# 无动作发布的纯平移预览
.venv/bin/python scripts/spacepilot_test.py \
  --enable-button 19 --mode translation --dominant-axis \
  --translation-scale 0.5 --rotation-scale 0 --debug-input

# 独立终端只读记录，首条非零手动指令触发45秒采样
bash scripts/record_control_response.sh
```

实际发送加 `--execute`，先预检接收端、按回车，再通过实体3启用；一次只运行一个动作发送程序。接收端 `manual_command_rate` 与发送端 `--rate` 必须匹配。匿名DDS兼容只接受参数服务验证后、各话题唯一且类型正确的匿名订阅，日志明确提示；它不能证明匿名端点的节点归属。

## 4. 19:32运动记录与结果

原始记录为 `local/diagnostics/control_response/20261017_193243_851241.json`，SHA-256：`e99b61c8f0e96501a0f6fe6a7e2108f8e9fe96f6fe9bcc6b863816663bca6403`。

接收跨度29.645秒，313条手动指令、1489条关节反馈、1488条EEF反馈。用户提前结束（interrupted），记录器无错误，四段主要前后动作完整。接收端200 Hz、动作10 Hz、模式3。用户反馈比之前稍好，但没有同条件前后对照，不能量化改善幅度。

| 动作 | 首个X指令至明显位移 | 全零后接近停止 | 全零后继续X移动绝对值 |
| --- | ---: | ---: | ---: |
| 第一次前推 | 0.354 s | 0.245 s | 0.784 mm |
| 第一次后拉 | 0.371 s | 0.220 s | 0.436 mm |
| 第二次前推 | 0.241 s | 0.299 s | 0.916 mm |
| 第二次后拉 | 0.410 s | 0.229 s | 0.680 mm |

起动定义：相对前0.3秒基线沿X动作方向移动≥0.1 mm且持续0.1秒。近停定义：绝对X速度<0.5 mm/s且持续0.2秒，速度使用100 ms位置差分窗口，存在约±50 ms平滑尺度；尾部位移取全零后约2秒。第二段X归零后有微小旋转，表中采用随后全部六维稳定归零时刻。

指令接收间隔中位数102.931 ms、最大104.549 ms；反馈约20 ms，无>100 ms空档。速度波形整体对齐偏移约0.12秒，相关系数0.992；不是纯网络延迟，起动阈值还包含输入逐渐加大的过程。第三段反馈X速度差分峰值约19.4 mm/s，超过名义15 mm/s；50–200 ms差分窗口仍约18.7–19.8 mm/s，提示追赶/超调迹象。

对应接收端日志 `~/.ros/log/python3_181314_1792236613237.log` 检查时无WARN/ERROR或SDK_REJECTED；不能据此证明未检查的SDK发送均成功。记录没有硬件松手时间、SDK接受目标或实际发送时间。四段X非零持续1.83/3.12/2.36/2.39秒，并非半秒阶跃，含其他平移/旋转；可证明可重复拖尾，不能单独分离SDK、阻抗、机械响应或显示延迟。

[对照曲线](../../../evidence/control_response_20261017/response.png) · [分析JSON](../../../evidence/control_response_20261017/analysis.json) · [复现说明](../../../evidence/control_response_20261017/README.md)。原始录制、SDK、环境和大录包留在Git忽略的本地目录，小型分析结果和曲线进入提交。

## 5. SDK和接收端排查结论

500 Hz现场日志累计六次SDK_REJECTED，均为clear_set返回0，待下发目标与反馈最大关节差约0.66–4.34°。安装副本与维护源码执行逻辑一致，差异仅为停止语义注释。`delta_splits=50` 在当前速度保持实现中仅兼容保留，不会排队走完50步。

检查时 `libMarvinSDK.so` SHA-256：`dd6b7afdbda8de3bafb6797c6f94547302ae60bf285ee8daa9762de45be636d6`。实际二进制及工作区SDK参考源码的对应分支表明：发送状态50/100（封包/待发）时OnClearSet返回false；OnSetSend将缓冲交给后台线程，DoSend调用sendto后清状态。因此clear_set=0是SDK本地发送状态忙的证据，不能简单称为控制器拒绝目标。为何忙超过周期、是否解释全部体感迟滞仍未测定。

当前尚未修复的两个工程缺口：clear_set失败后仍继续设置目标；send_cmd返回值未检查，就更新本地cur_joints。SDK提交成功也不等于控制器确认或实际到达。

普通零只清速度/have_goal，停止新增目标，不用当前反馈替换最后SDK目标；下一次IK继续以前一目标为锚点。因此反馈落后时可以继续追踪，不能把立即发零描述成物理立即停止。是否改为反馈位置保持，需要独立设计和验证。

模式3初始化设置K/D及SDK速度/加速度比10/10，其影响未定。500 Hz每轮2 ms；离线当前姿态FK/IK加包络FK中位数0.087 ms、最大0.131 ms，不含SDK和调度，不能直接认定逆解超时。0.63 ms服务往返、20 ms反馈节拍也不能代替运动时端到端测量。

## 6. 调整建议与待办

本次先固化，不提高刚度、速度或频率，不启用未经验证的自动反馈保持。200 Hz是当前操作基线，不是已证明最优值或物理即停保证。

1. 同一接收端时钟记录命令回调、clear/set/send耗时与返回值、本地目标、控制器报告目标、实际关节和帧号；后台写盘，避免控制循环逐条打印。
2. 区分SDK忙、设置失败与提交失败；明确本地目标在对应提交阶段成功后才推进。先离线故障注入，不用阻塞等待或发送旧动作掩盖失败。
3. 对照零指令、目标停止变化和反馈速度衰减，再决定停止策略、跟踪限幅或K/D；一次只改变一项。
4. 保留输入端模式、独立倍率、立即起停发送，暂不通过改轴或提高输入频率解决共同底层迟滞。

## 7. 提交前验证

本机 `PYTHONPATH=src:/usr/lib/python3/dist-packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest` 对SpacePilot、SDK换轴、接收端预检、手柄、tag跟随/标定、async/alternating/periodic和数据隔离等20个测试文件回归：**292 passed**。系统dist-packages提供本机OpenCV/SciPy，这不是通用环境安装方案。

只读记录器验证了真实参数和反馈接收、JSON保存；离线分析复现原始哈希和四段结果。接收端运行行为没有修改，仅纠正停止语义注释。软件测试、现场试用、内部标定残差和独立任务成功率是不同证据，不能互相替代。
