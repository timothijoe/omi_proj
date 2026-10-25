# 2026-10-24：独立原图与触觉面板V2

用户反馈原整图看板时延容易被误认为传感器故障，要求保留原版并开发新版。
新增V2脚本、独立RViz布局、分进程转换和独立接收诊断；不修改原版8个核心文件，哈希清单保存开发前基线。
不再每帧保存PNG；原图由RViz直接订阅，各路触觉派生图独立刷新，单worker失败不连带关闭其他面板。

首轮软件回归：V2、V1实时看板和grid回放共29项通过，覆盖原文件未变、源header与本机接收时钟分离、
CDR大小端/非法头、独立面板数值等价、坏数据、worker停滞状态及参数校验。
真实ROS隔离domain221合成测试通过：7路派生图实际订阅、坏A形变字段隔离、SIGSTOP暂停A形变worker、
单A剪切源停止、终止B深度worker后其他面板持续更新；控制topic为空，退出无子进程残留。
首轮测试工具曾用旧辅助函数生成32FC1消息，产生错误step；修正测试消息构造后完成复验，未修改生产解码规则。

证据：`local/diagnostics/live_grid_v2_20261024/headless_03/`，含nominal、坏数据、暂停worker、断流和退出记录。
所有源均为合成数据，不连接现场设备。实际GUI检查与后续修订另记本篇追加段。

功能与边界见[V2纪传](../evolution/grid-live-review-v2.md)，使用见[教程](../../../../tutorials/grid_live_review_v2.md)。
原图面板可能保留断流末帧，必须看接收诊断；同RViz进程仍共享GUI/GPU，不承诺硬实时或完全故障隔离。

## GUI及收尾验证

隔离domain222实际启动RViz和独立模型显示，通过同一组合成故障检查。首版截图发现模型区过窄、诊断文字过小，
调整为相机／A／B三行四列、默认隐藏左侧配置栏、加宽模型区及增大诊断字体；另提供`--window-size`适配较小屏幕。
最终目标窗口截图为`local/diagnostics/live_grid_v2_20261024/gui_03/rviz.png`，已实际查看：
12路图像面板、三维模型及诊断表可见，B深度worker被测试终止时，源仍RECEIVING而该面板WORKER_SILENT，其他图像持续更新。
本机image_transport对`/omi/tactile/{a,b}/raw`后缀给出泛化命名警告，但真实合成原图已显示；未擅自改源topic。

补充区分RENDER_BUSY与PUBLISH_BUSY，JSON保存最近128次绘图P95及累计最大值。
再次回归29项通过，Python编译、Shell语法与diff检查通过。最新无GUI复验记录在同根`final/`目录。
模拟源约30Hz、派生面板约10Hz的短测只验证调度和隔离，未测现场传感器或曝光到屏幕时延。
测试进程正常清理，未重启现场采集、未发送控制指令；本轮未自动commit/push。

## 后续：精简面板、外部ROI过期保留与EEF／控制信号栏

用户观察外部ROI反复闪烁。连续读取实际V2状态确认当时输入约0.7～1.1Hz、消息间隔约1～1.47秒，
ROI在OK／STALE之间切换；裁剪通常0.4～0.5ms，另有一次约185ms停顿。
500ms无新帧切换占位提示是主要闪烁机制；这只是当时接收窗口，不能直接判定相机硬件故障。
随后外部ROI改为保留末次有效像素、叠加红框与STALE秒数，新图到达恢复普通显示，不再整块闪黑。
此显示改变不修复网络或训练链路的旧图问题。

用户进一步要求去掉Wrist full、A raw、B raw，并增加EEF和控制信号bar。
V2改为三行三列九个观测面板，下方左侧诊断表、右侧独立EEF／控制栏：

- 末端XYZ毫米、ZYX RPY度数、源frame及接收年龄；无有效数据时不伪造零位姿。
- 人工／策略各自六维wire指令条形图，mm／SDK ABC度；不根据跨topic到达顺序推断控制权。
- 只读查询接收端参数以选择真实人工／策略话题，可显式覆盖；等待参数时EEF显示仍工作。
- 最近回执另列，接收／接受不冒充实测运动完成；指令过期变灰，非法指令显示BAD_DATA。
- 显示范围可调，超范围条形图截短、数字保留；不修改控制、采集或经验池。

35项V2／控制栏／V1／回放相关回归通过。隔离domain221真实ROS测试覆盖自动参数路由、
两通道数值与EEF单位转换、坏指令和单路断流，以及此前图像worker故障隔离；查看器控制publisher为0，退出无残留。
证据在 `local/diagnostics/live_grid_v2_control_20261024/headless/`。
本节的测试命令源是隔离域中的合成消息，不能解释为实际机器人控制验收；原V1仍保留。

后续实际GUI复验也通过，截图 `local/diagnostics/live_grid_v2_control_20261024/gui/rviz.png` 已查看：
九幅观测图、左侧模型及下方并排的诊断／控制栏均可见，EEF毫米与两路正负条形图显示正确。
原图/触觉单路故障隔离再次通过，查看器没有控制publisher，测试退出无子进程残留。
随后仅正常重启现场只读V2看板加载新布局，未重启传感器或Actor/Learner；新会话为
`local/grid_live_v2/session-zhuf_idb/`。布局和标记更新已同步教程与纪传体。

## 后续：相机／触觉面板整体消失的排查

用户明确是面板整体消失、只剩三维机器人。检查时没有运行中的V2／RViz窗口，未能现场复现。
最近`session-zhuf_idb`的结束来自此前主动Ctrl+C释放查看器占用，不能当成自发故障；
退出前源和绘图状态正常，RViz日志未记录崩溃。

发现V2模板及生成器只设置`Hide Left Dock: true`，遗漏`Hide Right Dock`。
核对[ROS Jazzy布局加载源码](https://github.com/ros2/rviz/blob/jazzy/rviz_common/src/rviz_common/visualization_frame.cpp)
和[Config读取源码](https://github.com/ros2/rviz/blob/jazzy/rviz_common/src/rviz_common/config.cpp)：
两侧读取复用同一bool，缺失键不写输出，因此右侧可能沿用左侧隐藏值。
已在模板及生成器显式补`Hide Right Dock: false`，运行时也为旧模板补缺省值。
这是确认的配置缺陷，但尚不能证明是用户“待着待着消失”的唯一触发机制。
另记录F11全屏会隐藏停靠面板，右侧箭头会折叠图像区；教程加入恢复方法。

验证：原有35项回归通过，运行时新模板与缺少右侧键的旧模板均输出false。
隔离domain222的实际ROS／RViz GUI检查通过，断流、坏数据、worker暂停和退出后
九幅观测图及诊断／控制栏仍在；截图已查看。
证据：`local/diagnostics/live_grid_v2_dock_20261024/gui/`（`report.json`、`rviz.png`及故障快照）。
测试退出无子进程残留，未留下占用现场domain13的查看器；原版及采集／训练逻辑未修改。

## 后续：末端反馈升级为独立一列bar

用户要求再增加end effector显示。原有末端信息位于控制栏顶部两行文字，本次将底部右侧面板
改成三列：END EFFECTOR（绿色反馈位姿）、HUMAN（蓝色人工增量）、POLICY（紫色策略增量）。
末端列提供XYZ mm与ZYX roll/pitch/yaw度数六根条及数值，显示源frame、接收年龄和状态。
条形范围±1500mm／±180°仅为固定显示比例，不是限位；数值保留真实幅度，超范围新鲜条变红。
末端超过500ms未更新时保留旧值并变灰／STALE；缺失或非法位姿显示横线，不伪造零值。
该列复用原只读末端订阅和control进程，没有新增控制发布或改变执行逻辑。

35项原有回归通过；额外渲染检查WAITING、LIVE、STALE、BAD_DATA末端状态，确认过期保留、非法清除。
隔离domain222实际ROS／RViz检查通过，截图已查看，三列完整可见。
证据：`local/diagnostics/live_grid_v2_eef_20261024/`，GUI报告与截图位于其`gui/`子目录。
测试进程清理完成；发现用户现场会话`session-tp_e_vz3`运行中，保留该会话，告知退出重启加载更新。
