# Training 当前摘要

最新阶段归档：[2026-10-07：共享编码器、HIL-SERL对齐与中断恢复](chronicles/2026-10-07-shared-serl-resume.md)。
包含实现范围、代码定位、版本兼容、测试证据和后续待办；给后续agent交接可先读此文。

2026-10-07：RL升级为`omi-hil-sac-shared-serl-v2`，保留当前输入（离线wrench关闭），
Actor/Critic真正共享编码器，Critic独占融合编码器梯度；官方式256×256头、LN/tanh、Xavier、
std[1e-5,5]、softplus温度、随机裁剪增强；默认batch256（可显式32）。
仍是PyTorch多模态适配，不是官方数值等价复现；输入融合/actor proprio梯度、限幅、奖励语义等差异明确保留。
旧BC头/加载兼容保持，旧v1 Learner不能直接resume到v2。没有运行新策略控制真机。
采集增加`--resume`按回合边界续写，staging孤立回合排除训练；离线支持多个`--source`目录。
训练SIGINT/SIGTERM延迟至完整更新后保存，周期checkpoint保留；dirty replay不自动恢复。
72项相关测试通过、2项CUDA跳过；含真实已采观测CPU更新/恢复及更新中中断测试。
操作与边界：[采集教程](../../../tutorials/rl_episode_collection.md)、[架构对齐](../../../tutorials/hil_actor_learner.md)。
以下2026-10-06训练结果属于v1，不代表v2已经完成正式训练或效果验证。

2026-10-06新增离线RL实际训练闭环：用户授权暂按现有标签有效，最新采集10段按回合划分
8段929条训练、2段222条留出；真实多模态SAC在GPU完成100次更新并保存重载，随后恢复续训2次至102。
入口`scripts/train_rl_offline.sh`，产物`local/rl_training/offline_20261006_v1/`；
操作及数值见[采集教程的离线训练部分](../../../tutorials/rl_episode_collection.md#2026-10-06离线sac训练流程已跑通)。
磁盘池两流各929（同组人工数据，不是独立倍增），Actor参数变化、冻结参数不变，重载误差0。
原始数据未变，不加载BC头、不发布机器人动作；按键缺陷未修复。
留出动作MSE没有改善、222条最终dx均为负，不能视为策略学会插入，禁止将流程验证误作部署验收。
下面“未训练/未入池”为此前阶段；此次新建了独立训练目录，未修改原session的ready/imported状态。

2026-10-06阶段归档：[RL回合采集、异步写盘与首批数据检查](chronicles/2026-10-06-rl-episode-collection-audit.md)。
用户已采3个session、16段1723条，全部通过只读结构/动作回执/观测连续性校验，未实际入池或训练。
最新10段1151条：2成功、6超时、2提前结束；成功是否真实仍待用户确认，约56%零动作、旋转全零。
已复现307/308短按被最终状态覆盖的缺陷，尚未修复；最早两段超时标签需隔离核实。
BC对新ready回合的加载适配仍待补；当前文件保存成功不等于训练语义全部合格。
以下为按时间积累的阶段记录；冲突时以上述最新归档及教程为准。

最新临时设置：collect_rl_episodes入口强制review=auto，成功/超时/307提前结束的有效回合自动保留；
304/305不参与当前采集流程，无需审核。后台保存完成后仍等315开始下一轮。
数据异常/写盘失败不进入训练池；下文人工审核描述为此前实现，能力仍保留在底层。

最新用户指定默认按键：315开始、308成功结束、307不成功结束（截断）；304保留、305丢弃、311 RB不变。
307与丢弃审核已分离，以下旧305终止描述为历史行为。按键配置属于回合契约，新采集使用新目录。

人工RL采集入口现已改为独立线程压缩/写盘/fsync，主线程只复制快照并提交32条有界队列。
结束后人工304保留/305丢弃，未审核与未写完前不允许开始下一轮、不发布ready。
运行中305改为手动终止（截断），不会直接丢弃；异常/队列满仍排除训练。
审核与后台排空期间继续处理RB复位。此改动仅接入collect_rl_episodes新入口，
旧hil.actor及旧demo采集仍用同步EpisodeSpool/各自存储，不声称全部在线训练入口已迁移。
下文自动保存描述为此前阶段，当前以人工审核教程为准。

新增[人工RL回合采集入口](../../../tutorials/rl_episode_collection.md)：不依赖模型/learner，
开始按钮→成功或15秒超时→零动作停止、自动保存→RB人工复位→再次开始。
成功/有效超时均保留完整transition，复位不入池，异常段排除；Ctrl+C保留审计前缀。
新入口走实际手动话题，新增带ID的manual回执，执行前检查接收端协议和手柄。
旧接收端不支持时拒绝启动；没有替换现场进程或实机验收。物理复位仍由人工完成。
在线Actor另补回合外手柄复位和命令间成功停止；尚未统一其全部人工路由/模型迁移流程。

最新阶段已归档：[现场后退诊断与无wrench对照](chronicles/2026-10-05-policy-input-audit-no-wrench.md) →
[当前运行/录制教程](../../../tutorials/no_wrench_policy_record.md)。用户已试运行带wrench模型，现场观测225窗口完整保存，
离线逐窗复现后退；wrench基线差异明显。已重训无wrench第1000步模型（341训练/161验证），
同一215完整现场窗口仍全负X，幅度有所减小，**方向问题未解决、无闭环成功率**。
新独立入口`run_no_wrench_policy_record.sh`默认训练最佳`actor_train_best.pt`，不改变旧脚本默认模型。
下文“未执行真机”等为当时助手开发验证边界；用户后续现场实验以上述最新记录为准。

时间检查说明：手柄策略wrapper的RGB 500ms分别约束入口header年龄和采样时本机接收年龄，底层默认仍为250ms。源时钟尚未确认；外部RGB专用接收时间策略仅讨论、未实施，两种年龄差大不直接判定无延迟。见[时间基准纪传体](../hardware/evolution/sensor-time-alignment.md)。

实时入口更新：外部RGB默认500ms（`--rgb-max-age-ms`可调，其他输入不放宽）；
执行时`--manual-topic auto`读取接收端manual_delta_topic并核对真实订阅，兼容现场
`/omi/controller_test/decision`。手柄轴/RB/设备与接收端检查失败则不启动发布进程。
本次仅软件与隔离环境验证，未操作真机。

最新实时入口：[wrench BC＋RB手柄仲裁](../../../tutorials/wrench_policy_gamepad.md)，
`bash scripts/run_wrench_policy_gamepad.sh --output <新目录>`默认预览，显式`--execute`发布。
用户要求默认policy-scale=1.0，保留5mm/s、5°/s范数限幅；接收端须订阅两个独立模型/手动话题。
双侧完整wrench历史门控、旧候选丢弃与RB优先回归已覆盖；真实包146样本观测逐字段一致、
CUDA检查点推理一致。未执行真机运动，输入门控不等于峰值保护（后者仍默认关闭）。

2026-10-05最新：[日期bag含wrench的BC训练已完成1000步](../../../tutorials/passive_bag_bc_wrench.md)，
见[本次编年](chronicles/2026-10-05-passive-bc-wrench.md)。四包生成1005条有效样本，
前三包844条训练，最后一包161条验证；第三包503条BC配对取代预览专用335条的训练限制。
模型保留双相机/三场触觉/EEF十帧结构，新增双指wrench[10,2,6]和mask进入MLP融合，
训练集独立归一化。数据在`local/passive_bc_20261005_wrench`，CUDA训练在同名前缀
`_train_v1`目录，1000步/batch32/lr0.0003；进度/完整结果见progress/history/report JSON。
监督是记录指令，不是执行回执；自动返回和成功标注仍未确认，不当作RL transition或成功率证据。

当前现场采用**独立gamepad遥操作＋纯录包**。先看[操作教程](../../../tutorials/demo_bag_dataset.md)、[当前数据契约](evolution/demo-collection-bc.md)和[四包检查记录](chronicles/2026-10-05-passive-demo-audit.md)。以下较早条目保留阶段历史，以此处入口为准。

- `record_demo_bag.sh` 不读取手柄、不发布控制；默认明确topic列表，包含 `/omi/controller_test/decision` 与双指wrench，Ctrl+C或duration停止，不用execute/episodes。
- 用户四包已检查：17.42/22.78/52.48/22.32秒，原始观测和指令完整，使用控制端消息定义后全部解码通过；少量时效异常需清洗。
- 原第三包335条strict观测/实际wire配对预览仍为review-only，240条非零；其16.9秒跳跃不能当连续轨迹。新增BC转换独立生成503条因果观测/指令样本；无ID/回执、成功或返回段标注的限制仍保留。
- 查看器左列双相机/动作/时间，右列最上方六维力/力矩和曲线，下方三场触觉；四位小数、←/→切帧并暂停、历史槽和next observation切换、PNG导出。入口 `local/four-demo-audit-20261005/preview-204949/`，示例 `http://127.0.0.1:8767/?step=242`（需启动服务）。
- 三场触觉使用10Hz十帧，当前＋过去9帧；本次BC recipe已将wrench历史正式接入网络，旧recipe保持原输入兼容。旧在线观测入口尚未提供此新checkpoint的wrench历史。
- 先前10秒只读测试生成70条真实观测/全零占位预览，RGB header age中位约490ms，strict完整窗口0，只用于诊断。它与本次四包真实指令数据区分。
- 集成collector及其快照转换/BC仍作为另一入口保留，软件和合成训练闭环通过。当前独立gamepad包没有其sample/event消息，不能直接使用快照转换器；新增 `passive_preview` 提供真实wire审阅格式。

2026-10-05进展已归档：[HIL环境、SAC与Actor/Learner当前专题](evolution/hil-actor-learner.md) → [操作教程](../../../tutorials/hil_actor_learner.md)。
三项软件实现完成，当前处于真机联调前阶段。下一步依次验证现场观测、按钮/计时、动作回执、短回合入池及learner更新；尚无真实插入成功率或收敛结果。

2026-10-05新增[六维真机HIL环境、SAC与Actor/Learner](../../../tutorials/hil_actor_learner.md)。
ROS reset/step、开始后15秒计时、人工成功/整段入池审核、无夹爪Actor/双Critic/目标网络、
两进程磁盘交接与权重发布已实现。复用冻结ResNet-10＋视觉触觉EEF十帧结构；
默认ROS只读，尚未启动真机训练。42项软件测试通过（含真实多模态梯度与独立进程闭环）；
CUDA专项3项及接收端/保护48项通过；另有既有消息schema测试环境问题。后文“真机组装/learner未接”是早期阶段记录。

2026-10-05新增[完整transition磁盘导入与在线分流API](../../../tutorials/transition_replay.md)。
复用DiskHILReplayBuffer，指定目录、逐行JSONL、契约检查、episode/时间落盘；
成功离线human只进Demo，在线policy进RL，在线human进两流。相关26项测试通过。
当前BC代理标签不能直接当执行命令导入；真机配对、reward/episode及learner仍未接。

2026-10-05新增接收端源码证据：[控制端迁移与审计](../hardware/evolution/robot-controller.md)。原端将ABC各分量除20再重复IK，且从上次命令目标继续，与反馈锚点代理标签不同；此前单次SDK数学审计不能覆盖整条执行链。当前限幅与模型保持不变。

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
