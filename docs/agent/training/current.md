# Training 当前摘要

2026-10-05待解决：用户指出当前动作限幅仍有不足，orientation与rotation尚未完全统一，需进一步核对其具体含义、表示转换及限幅衔接。仅记录，未修改控制代码；见[动作缩放策略](evolution/policy-action-scaling.md)。

动作缩放讨论已归档：[分别限幅与统一缩放](evolution/policy-action-scaling.md)。为保留policy平移/旋转比例，建议共用缩放系数；目前仅讨论和记录，代码仍为分别限幅。

最新动作处理：policy先乘policy_scale，再对平移和旋转向量分别保方向等比例限幅到执行上限（默认1mm/1°每步），不再因执行超限直接拒绝。未缩放实验异常边界、输入时效、完整历史和RB优先仍保留。99项相关测试通过，本次未启动真机；详见[policy教程](../../../tutorials/policy_gamepad.md)。

最新：[实时 policy＋RB 接管＋SDK 转换](chronicles/2026-10-04-policy-gamepad-integration.md)已接通。用户确认左臂/FRAME_BASE=0；30秒GPU预览280次推理，234条候选被仲裁选择，未发真机动作。90项测试与1525条GT数学核对通过；EEF临时补偿可显式用于输入，现场TCP及安装方向仍未完成运动标定。下文“未接入”“EEF阻塞”和旋转向量实机接口均为早期状态。

手柄输出 wrapper 已支持显式 `--output-convention sdk-x-forward-z-left`：按假设安装方向 `(x,y,z)→(x,-z,y)` 并将旋转向量转 SDK ABC；默认 legacy 不转换。终端现同时显示原始值、转换状态和最终值，67项相关测试通过。接收端 FRAME_BASE/UserFrame 与实际安装方向仍待核对，用户曾报告旧映射左推导致上下移动，尚未完成换轴后的现场验收。详见[手柄教程](../../../tutorials/gamepad_control.md)。

新增[独立手柄动作选择节点](../hardware/chronicles/2026-10-04-gamepad-intervention.md)：六维映射、RB 按住接管、带时间戳的策略候选选择已实现。现有 `stack_shadow` 仍只读，尚无候选发布者接入；真人干预的真机 transition、经验池和在线训练闭环尚未实现。相关测试 37 通过、1 跳过，实际机械臂动作尚未验证。下文早期“ROS 人工接管尚未实现”记录应结合本次阶段更新阅读。

新增[无关节模型实时影子入口](chronicles/2026-10-04-stack-live-shadow.md)：`run_stack_shadow.sh`读取现场双相机/双指三场/EEF，CUDA计算，仅写本地文件，无动作发布者。19项测试及GPU离线一致性通过；现场strict30秒受EEF时间戳影响，随后诊断30+60秒EEF发布中断，实际推理0次。**实时输入尚未跑通，待EEF恢复及时间问题排查**；末端几何对齐遗留保留。见[操作教程](../../../tutorials/stack_shadow.md)。

新增[不使用关节反馈的GPU历史拼接模型](evolution/nojoint-stack.md)：2000步完成，best1300步验证0.790943mm/0.00321688rad；joint_enabled/mask固定0，末端位姿保留。相对原模型平移高2.48%、旋转低0.44%；单seed、CPU/GPU条件不同。后续影子接入进展见上文，未接执行器。


新增CUDA离线测速：独立`local/cuda-env`，同版本PyTorch2.14.0下当前拼接模型CPU平均27.74ms、CUDA平均7.22ms/P95 9.15ms，约3.84倍加速。FP32、包含输入输出传输、CPU/GPU数值核对通过；未接入在线。见[实验记录](evolution/current-stack-history.md#2026-10-04-cuda-推理对照)。

新增[六关键点候选与人工审核工具](evolution/six-keypoint-review.md)：12图已导入，29个几何候选；真实目标身份尚未确认，0/72命名建议、无人工真值。22项测试和浏览器交互回归通过，不修改policy或启动训练。

新增[当前帧独立＋过去9帧通道拼接、去掉GRU](evolution/current-stack-history.md)：
同划分完成2000步，最佳700步验证0.771823mm/0.00323121rad、归一化MSE0.790969。
较ResNet＋GRU最佳分别降低8.37%/2.07%，单种子结果改善，后期仍过拟合。
当前视觉骨干冻结，历史27通道首层可训练；触觉和状态保留10帧，尚未接入在线节点。
正式产物`local/eef_history/oct04_current9stack_run2/`。
同场2线程CPU推理平均27.34ms、P95 29.12ms；原ResNet＋GRU缓存路径10.00ms，
因此此次验证性能改善伴随在线计算开销增加，详见实验说明。

新增[冻结ResNet-10＋GRU实验](evolution/resnet10-history.md)：官方ImageNet权重已下载并转换核验，
原004/008验证划分重训2000步，最佳100步0.842298mm/0.00329936rad、归一化MSE0.874630。
相对旧CNN最佳误差下降约0.49%/2.41%，单seed小幅改善，后期仍过拟合；未加入定位辅助训练或在线接入。
产物`local/eef_history/oct04_resnet10_run1/`，操作见[教程](../../../tutorials/resnet10_history.md)。

后续硬件动作接口以用户已实机测试的 `axis_test.py` 为参考：10 Hz、六维增量、mm/度。现有策略为m/rad；**用户指定暂按基坐标系旋转向量对接（假设，尚未核实接收端）**。单位换算、跨基坐标系变换及TCP区别已单独注明；增量累加语义仍待核实，尚未启用控制桥接；见[对齐方案](evolution/axis-controller-interface.md)。

新增[在线历史 policy 与可选 wrench](evolution/history-online-policy.md)：10 Hz 因果窗口、reset、缺帧 mask 和 Float64MultiArray 影子候选；wrench12 + enabled2 + mask2，无效或禁用严格置零。旧 v3 权重可禁用 wrench 在线推理，v4 完整观测历史池与训练输入已实现，尚未重训。见[教程](../../../tutorials/eef_history_online.md)。

当前数据、历史模型设计、基线定义及200/2000步训练降幅见[实验与设计总结](evolution/oct_03-experiment-design-summary.md)。

用户说明bag_002包含很多尝试，现移入训练，验证改为bag_004/008（1283训练/242验证）。
单帧和历史模型均从头重训2000步；最佳历史200步验证0.846mm/0.003381rad，
平移优于零动作约16%，旋转接近基线；继续训练仍过拟合，尚不能证明恢复策略泛化。
当前产物`local/eef_history/oct03_split2/`，见[新划分编年](chronicles/2026-10-03-validation-resplit.md)
及[oct_03日志](evolution/oct_03-training-log.md#第三轮用户说明bag_002包含反复尝试调整验证划分)。

此前旧划分已完成最近1秒历史＋GRU的2000步训练，保留原8/2包划分与1525样本。
最终验证1.011mm/0.004215rad；最佳100步0.907mm/0.003405rad，仍仅接近简单基线。
验证曲线显示后续过拟合，屏蔽历史反而改善，尚未证明学到受阻退回。
两轮集中维护于[oct_03训练日志](evolution/oct_03-training-log.md)，
完整验证与产物见[历史GRU编年](chronicles/2026-10-03-history-gru-training.md)。

oct3正式10包已审计并导出1525样本，用户确认后完成首轮2000步训练。
1135训练/390验证；验证平移1.037mm、旋转0.004172rad，均未优于零动作/均值动作基线。
模型、训练曲线与分包预测已保存，检查点重载一致；见[首轮结果](chronicles/2026-10-03-formal-training-run1.md)。
新增离线v3小矩阵/腕部ROI输入：state14，排除无消息wrench，按录包接收时间对齐并保留原header。
跨设备时钟偏移、旧相机帧及bag_009间断见[本轮记录](chronicles/2026-10-03-formal-dataset.md)，
操作见[教程](../../../tutorials/oct3_formal_dataset.md)。

新增[动作 rosbag 与模拟控制端联调](../../../tutorials/eef_action_bag.md)：
Float64MultiArray六维增量，XYZ各5cm、三轴各10°、逆序返回，240帧实收与目标比对通过。
目前验证到模拟目标位姿，未接真实末端控制器；见[联调记录](chronicles/2026-10-03-action-bag.md)。

末端策略已新增[可选腕部输入](evolution/eef-action-space.md#v2可选腕部相机与输入源标记)：
两路RGB各3×128×128，camera_mask为2维，off/required/optional写入版本契约。
bag_004双相机、关闭和optional缺腕部三种场景各两轮140条影子候选通过；
全量流回放曾超时，当前v2使用原始选中帧验证输入链路，不代表全量吞吐验收。

新增[左臂末端动作空间](evolution/eef-action-space.md)：6D基座系增量、未来状态变化代理标签、
独立版本BC与类型化ROS候选。bag_004导出69样本，500步单段拟合，两轮140条影子候选验证通过。
旧七关节BC兼容；未实现人工接管选择、真实控制或独立泛化验证。

已补充[原版 HIL-SERL 接管与经验记录](evolution/hil-serl-reference.md#人工接管动作记录与训练采样)，
并记录[ROS 类型化动作与统一选择方向](../../design/bag-bc-shadow-policy.md#人工接管与类型化动作接口待实现)。
旧关节BC影子预测仍为String JSON；新EEF实验已有类型化策略候选，ROS人工接管链路尚未实现。

新增[录包BC与ROS影子推理](evolution/bag-bc-shadow.md)：真实导出108个样本，500步CPU训练，
同段RMSE降至0.001781 rad；两轮ROS回放218次预测且输入精确一致。
这是单段过拟合/消息链路验证，无独立成功示教验证，不证明插孔能力。
动作绝对弧度语义待确认，只输出shadow预测，不使用腕部/夹爪/TCP。
入口 `scripts/bag_bc.sh`，见[教程](../../../tutorials/bag_bc_shadow.md)。

已增加 [磁盘经验池](evolution/disk-replay.md)，使用 memmap、后台 batch 预取、双流 ring 和干净检查点恢复，训练通过 `--replay-backend disk` 选择。40 项自动测试通过；A 臂 200 步完成 SAC/BC 更新与容量覆盖，短跑不证明策略收敛。图像字段通过合成数据验证，视觉任务、超内存冷盘性能及真机尚未验证。

原版任务及 USB 的动作、奖励/超时、SpaceMouse、观测 shape、RTX 4090、Buffer 与视觉网络核查见 [HIL-SERL 参考](evolution/hil-serl-reference.md)。USB 环境和视觉策略尚未接入 OMI。原版两个池填满的图像数组约 98.3 GB，是源码估算；在线网络约 9.38M、奖励分类器约 6.09M，骨干冻结、投影和控制头可训练，融合特征 832 维。最新补录见 [USB 资源与网络记录](chronicles/2026-10-02-usb-resources-and-network.md)，原始融合维度勘误见 [首次记录](chronicles/2026-10-02-hil-serl-reference.md)。

目前使用单进程 SB3 SAC、可选示范 BC、在线/示范双流回放和 JSONL 录制。训练中的干预来自脚本教师，覆盖整步七维动作后经过共同限位入口；真人键盘覆盖用于已有策略的逐步运行与录制，尚未接入在线训练。训练奖励为 TCP 距离进度、每步惩罚和成功奖励；独立评估使用稀疏奖励。经验池保存最终命令动作，默认每批在线/示范各半。

最新机制、参数和限制见 [HIL 训练纪传体](evolution/hil-training.md)。本机环境最近的 1500 步低熵纯 SAC 复验完成 1400 次 SAC 更新、0 次 BC 更新，固定评估 0/10 → 10/10，独立 30 回合为 30/30；仍使用脚本示范和接管。26 项测试已在配置本地 A 臂场景的环境通过。历史默认熵纯 SAC 失败对照见 [四项审计](../../hil_rl_reproduction.md)。真人连续干预、真机反馈与 LeRobot 分布式 actor/learner 尚未接入。

形成过程见 [首期编年](chronicles/2026-10-01-hil-sim-training.md)、[双流审计](chronicles/2026-10-01-policy-improvement-audit.md)、[低熵实验](chronicles/2026-10-01-low-entropy-sac.md)、[本地环境复验](../simulation/chronicles/2026-10-01-omi-environment.md)和[实现文档核查](chronicles/2026-10-01-training-implementation-docs.md)。
