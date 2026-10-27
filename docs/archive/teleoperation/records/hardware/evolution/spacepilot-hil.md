> 历史资料：原路径 `docs/agent/hardware/evolution/spacepilot-hil.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/teleoperation.md)；本页保留原过程与证据。

# SpacePilot 作为 HIL 人工输入

2026-10-17晚间最新：用户完成新采集、BC6148训练和在线RL启动，当前主setting夹爪开启、marker暂关。完整训练结果与23:29快照见[训练纪传](../../../../online-rl/records/training/evolution/spacepilot-bc-online-rl.md)，时间线见[编年](../../../../online-rl/records/training/chronicles/2026-10-17-spacepilot-bc-online-rl.md)。数字3总开关和Marker独立节点仍未实现。

2026-10-17新增，操作见[教程](../../../../../../tutorials/spacepilot_hil.md)。用户要求在BC/RL采集及在线交互中使用3D鼠标，同时保证原手柄仍能使用。

## 架构和兼容

`real/operator_input.py` 提供输入选项、profile校验、SpacePilotInput和SpacePilotHILMapping。默认gamepad分支仍创建原LinuxGamepad/Mapping；SpacePilot显式启用时不创建或打开Linux joystick。

SpacePilotInput向原Actor提供相同的 `poll/buttons/button_events/button_map/axes/error/close` 访问方式。按钮转换为原逻辑码，六轴保留独立连续量，由专用mapping读取，不借用会把Z/Rz量化的十字键映射。仅原RosTransport创建ROS节点及发布者，既有手动/策略路由不变。

已接入collect_episodes、bc_rollout、async_training、alternating，以及旧demo collect/actor。原CLI默认、手柄动作与按键含义保留；SpacePilot无法在fake配置中静默生成假示范。当前一键启动菜单仍保留其原手柄流程，SpacePilot使用直接入口参数。

## 按键与配置

默认逻辑码：311接管、315开始、308成功、307结束、314回位、304夹爪关闭/审阅保留、305夹爪打开/审阅丢弃、310标签修饰键；LB+304切换跟随，LB+305保存关系。原入口未启用的功能不会因换设备自动开启。

本轮实测后的用户预设为Menu0→接管、数字1 ID12→开始、ALT23→成功、Ctrl25→普通结束、ALT对称26→回home、Esc对称28→夹爪闭合、Ctrl对称27→夹爪张开、ID8→跟随切换、ID2→保存关系。Menu的0来自两轮按动顺序，首次预览需复核。原数字3 ID19在预设中未绑定。

预设副本在configs/spacepilot_hil_oct17.json，实际默认profile在local/spacepilot/hil_buttons.json；required_review=auto拒绝在旧人工审阅模式中使用，避免305与中止/丢弃语义冲突。原手柄与旧profile行为保留。`configure_spacepilot_hil.py --preset oct17`只需再采集开始键，支持--start-button-id；--direct-follow支持自定义独立标签键。已有文件不覆盖。

独立标签逻辑码65536/65537必须成对且不与回合事件重叠。DirectFollowButtons只在标签选择器内部复用原LB+A/B仲裁，虚拟组合键不进入夹爪或审阅；接管、结束、断连、回位仍优先停止跟随。FollowButtons纯逻辑抽取到follow_buttons.py，旧导入兼容，预览不依赖OpenCV。26/27/28的驱动特殊动作均为0，HIL不会用它们改变六轴模式。

profile schema为omi-spacepilot-hil-input-v1，buttons的key为原逻辑码字符串、value为libspnav ID；含固定axis_frame。要求311存在、实体ID唯一、键值合法。运行前检查当前功能所需的所有逻辑码，SpacePilot预检另验证接收端授权、base与频率；保留对唯一匿名DDS订阅的可选兼容。预检得到的profile SHA与运行构造时必须一致。

## 动作和数据

速度方案由--spacepilot-speed-profile控制。session保持HILConfig的step×hz基准及既有动作范围；standalone使用独立工具的10 mm/s、10°/s基准。auto在未指定config的新建人工采集中选择standalone，并在新建时扩展必要的action_scale；已有模型及显式config选择session，续采读取保存的方案。旧checkpoint/replay不静默修改，显式standalone超出其范围时拒绝启动。沿用死区、坐标映射和单轴滞回，SDK转换仍只发生一次。

HIL CLI的SpacePilot倍率默认1.5/0.3，新增--translation-scale/--rotation-scale简写；手柄速度不受其影响。

动作来源继续为human/policy，人工/策略仲裁、奖励与episode语义不变。SpacePilot trace补充operator_input来源/profile哈希/倍率/边界，遥测也带输入来源；已有gamepad遥测字段保留兼容。profile切换只影响下一次启动，不在线修改旧数据或模型。

输入过期150 ms时只归零人工候选，仍按接管归属记录；断连和250 ms轮询停顿清状态并触发原断连流程。启动/重连时按住的键需释放再触发；短按及同批按下/松开保留有序事件。接管释放在在线RL中是归还policy，不是总停机。

## 参考独立工具的响应调整

用户要求先备份后修改，基线提交为7c2d2c5。对照初版实际采集记录spacepilot_test_20261017_211128与211316，非零连续发送间隔分别98.6–102.3ms和95.9–104.9ms，未见长时间发送停顿。主要差异为较低且更早饱和的速度范围，以及启停等待观测节拍。这两次实际平移倍率为2.5，而单轴仍被限制到约5.77mm/s。

MotionSchedule由spacepilot_test.py与HIL共用：零/非零边沿立即发送，连续运动墙钟10Hz，不因方向变化加发，不补发积压。periodic人工采集、immediate仲裁下的人工接管及回合外调整使用该调度；after-inference仍遵守推理后仲裁，receipt入口仍遵守旧配对流程。手柄调度保持原行为。

额外发送允许复用最新观测但不伪造训练步。manual_timing标记对应片段必须观测递增、实际指令间隔80–150ms且无外部中断，其他片段只审计并分段；actual_command_interval_s记录真实间隔，终止边界用停止时刻。新建standalone采集的较大动作范围随数据保存，不能直接混入旧动作范围模型的回放池。

## 验证范围

测试覆盖默认手柄映射等价、两后端相同发布路由、六轴模拟量、动作限幅和原契约不变、短按、重连抑制、断流、回位/夹爪/LB组合键、after-inference接管/还权、人工采集标签、trace来源及所有入口help。真实驱动只读连接通过；测试临时ID配置已销毁，不是用户的物理键位配置。

最终合并回归409 passed、3 skipped（普通环境未加载rclpy，以及两项CUDA条件）；加载ROS环境后，隔离domain的消息/录包测试另有4 passed。CUDA两项未执行。

后续用户九键预设、单键标签操作和倍率简写落地后的相关回归319 passed、2 skipped（CUDA）。覆盖手柄/SpacePilot两种工厂接线、单键保存/跟随实际控制流程、按键不串入夹爪/回合事件、自动保留约束及模式图标键不改变六轴。新预设真实驱动只读连接通过。

响应调整后的相关回归341 passed、2 skipped（当时测试解释器CUDA不可用）。新增逐轴及随机六轴输出与独立工具等价、快速启停、不补发、旧模型范围保护、真实格式审计及训练导出验证。随后用户完成10回合新采集，9个正常回合用于CUDA BC，继而启动在线RL；详情见上方训练专题。软件数值等价不等于物理响应完全相同，SDK停止拖尾仍未修复。
