# 实时观测 V2：独立原图、触觉面板与延迟诊断

在 `omi_proj/` 中运行：

```bash
bash scripts/view_grid_observation_live_v2.sh --hz 10
```

原版仍用 `bash scripts/view_grid_observation_live.sh --hz 10`，原脚本、绘图源码和 RViz 配置未修改。
V2 是独立入口，不自动替换旧版。不必同时开两版；同时运行会增加订阅、CPU 和 GPU 负载。
默认 domain13，订阅已经运行的传感器；不启动设备、SDK、录包、策略或机器人控制。
关闭 RViz 或 Ctrl+C 退出本次查看器及其子进程，不停止外部采集进程。

## 布局与刷新

同一个 RViz 窗口中有独立的 Image 面板，可拖动、调整大小并保存自己的 RViz 配置：

| 行 | 内容 |
| --- | --- |
| 相机 | 外部原图、外部128 ROI、腕部ROI |
| A指 | deformation箭头、shear箭头、depth热力图 |
| B指 | deformation箭头、shear箭头、depth热力图 |
| 下方左侧 | 独立接收与绘图诊断表 |
| 下方右侧 | EEF位置／姿态、人工／策略六维控制指令条形图、最近回执 |
| 三维区域 | 原方向修正版 Stand、EEF/L7；沿用原显示假设，未标定TCP |

2026-10-24后续按用户要求移除Wrist full、A raw、B raw三个面板及其订阅，保留九幅观测图；不改变上游传感器配置。
外部、腕部图像由 RViz 直接订阅，不经过 Python 拼图。外部 ROI 和六路触觉派生图分别由独立进程生成，
每路只保留最新待处理消息，不积压绘图任务。`--hz 10` 是每路派生图的最高转换频率；原图更新由源topic和RViz决定。
没有新消息就不重复绘制有效图。断流超过500ms时派生图切为STALE；外部ROI保留末次有效像素，
叠加红框和STALE秒数，不再整块清空闪烁。该过期标记最多2Hz更新；新的有效帧恢复普通显示。
触觉派生图仍显示STALE占位，坏数据只影响对应面板；保留旧图仅用于观看，不表示图像恢复新鲜。
这里的500ms是查看器显示诊断阈值，不修改策略输入或控制端超时。

**RViz直接显示的原图断流后可能保留最后一帧；卡死／退出的绘图worker也无法自己清除旧图，必须同时看诊断表的RX age/STALE或WORKER_SILENT。**
同一个RViz进程仍共用GUI/GPU，独立面板不等于屏幕呈现或整机资源完全隔离。

原图必须由上游实际发布：

- 外部：`/camera/camera/color/image_raw`。
- 腕部ROI：`/omi/wrist/color/image_roi`。
- 三场：`/omi/tactile_grid24x16/{a,b}/{deformation,shear,depth}`。

需要其他腕部图像话题时可显式指定 `--wrist-topic /实际图像话题`，只修改第三个相机面板。
V2不会重启相机、切换上游配置或把ROI冒充完整图。
原图显示缩放不会改写原topic。形变/剪切保留原数值单位、方向和固定比例尺，depth继续使用0..0.3固定色标。

## 判断卡顿在哪里

如果相机／触觉的**标题和面板一起消失**，只剩三维模型，先检查RViz布局：

- 菜单／工具栏也消失时，按F11退出RViz全屏；此模式会隐藏停靠面板。
- 菜单还在而右侧九幅图整体消失时，点击三维区右边缘的展开箭头。
- 仍未恢复时，退出本次查看器，再运行上述V2命令，重新加载默认布局。

2026-10-24修正了V2布局遗漏`Hide Right Dock: false`的问题：RViz加载时可能沿用
`Hide Left Dock: true`的值，收起右侧图像区。生成器、模板及运行时缺省值均已补齐。
这是已确认的布局缺陷；尚未复现用户描述的“运行一段时间后自行消失”，不能断言它是该次现象的唯一原因。
断流、坏数据或单个绘图进程退出只影响面板内容／诊断，不会由V2程序移除整个面板。

| 字段／状态 | 含义 |
| --- | --- |
| RX Hz | 独立轻量进程最近3秒的消息回调到达频率；不是设备内部采样率 |
| RX age | 本机距上次消息回调的单调时间 |
| Gap3s | 最近3秒记录到的最大相邻回调间隔；永久停止时应结合RX age |
| Header | 本机ROS时间减源header；时钟未校准时不能当作端到端延迟 |
| Out Hz | 独立探针实收的派生面板输出频率，包含状态占位图；direct表示原图直接订阅 |
| Draw | 最近一次该面板解码、校验、转换绘图耗时 |
| RX->pub | 绘图进程收到消息至publish调用返回的耗时；不含此前网络、曝光或RViz呈现 |
| RECEIVING | 独立探针持续收到消息，不表示图像载荷或传感器物理状态已验收 |
| BAD_DATA | 对应派生图解码、尺寸或有限性检查失败，详细异常在status.json |
| RENDER_BUSY | 绘图持续超过500ms，但worker心跳仍可收到 |
| PUBLISH_BUSY | 面板图像转换／publish阶段超过500ms，区别于绘图计算停滞 |
| WORKER_SILENT | 超过2秒未收到该绘图进程心跳，可能卡住、退出或其状态通信中断 |
| STALE / STALE_RESULT | 源在该worker处断流，或转换完成时数据已超过显示时效 |
| PROBE_SILENT | 诊断表没有新的独立探针报告；旧表格数值不能当作实时状态 |

例如RX约30Hz且RX age很小，但某路Out Hz下降、Draw升高，应先查该路绘图。
若该路RX age持续升高而其他路正常，应查该路发布/传输/接收链。
各路RX和Out都正常但屏幕卡顿，则进一步检查RViz、GPU与桌面显示。
这些用于缩小排查范围，不能仅凭接收统计就断定传感器硬件故障；图像内容冻结且持续换时间戳也可能无法从计数发现。

## EEF与控制信号栏

底部右侧面板从左到右为三列：**END EFFECTOR（末端反馈）、HUMAN（人工指令）、POLICY（策略指令）**。
末端反馈现在有独立的一列六根条形图及数值，替代此前面板上方的两行位置／姿态文字。
绿色表示当前末端反馈，蓝色表示人工指令，紫色表示策略指令；过期变灰并标STALE。
末端的XYZ是源frame下的位置（mm），R/P/Y分别是roll/pitch/yaw（°）；人工／策略是每条命令的增量。
末端条形显示范围为±1500mm／±180°，仅用于显示，不代表机器人工作范围或运动限位；
超范围时新鲜数据的条截短变红，旁边保留真实数值。三列尺度不同，不能按条长比较末端位置和指令大小。

独立进程以最高10Hz绘制该栏，与相机／触觉转换、接收探针分开。这里只订阅数据，
仅发布 `/omi/live_grid_v2/control_bar` 显示图及 `/omi/live_grid_v2/control/status` 诊断JSON。

- EEF来自 `/tj/info/eef_left`，XYZ显示毫米，姿态显示ZYX约定的roll/pitch/yaw度数；
  原四元数与frame保存在JSON，显示实际源frame。RPY有通常的欧拉角奇异性，不作为控制输入。
- 人工、策略两栏分别展示最近收到的Float64MultiArray六维wire指令：dX/dY/dZ为mm，dA/dB/dC为SDK ABC度。
  这是每条命令的名义增量，不是实测位移、绝对位姿或速度；SDK命令frame与EEF参考frame可能不同。
- 默认通过 `/delta_ctrl_node/get_parameters` **只读**获取`delta_topic`、`manual_delta_topic`、`delta_frame`和`arm`；
  因而兼容现场 `/omi/controller_test/decision`。服务未出现时继续显示EEF并等待，不猜测或发布控制话题。
- 可用 `--manual-topic /实际手动话题 --policy-topic /实际策略话题` 显式覆盖显示订阅；
  `--receiver-node`可选择参数服务节点。不调用参数修改／运动服务。
- 两栏独立更新，迟到的另一通道零指令不会覆盖本栏。**不根据最后到达的topic推断实际控制权**。
  `/omi/action/receipt`另显示最近一条回执的来源、接受标记及状态，回执不代表机械臂完成运动。
- 指令250ms、EEF／回执500ms未更新则标STALE并显示旧值；末端和指令条变灰，不补造零值。
  这是显示诊断阈值，不修改接收端超时。坏数据为BAD_DATA，未收到为WAITING。
- 人工／策略条形图默认范围±1.5mm／±1°；`--command-translation-range-mm`和`--command-rotation-range-deg`
  只调整显示尺度。超范围条截短并变红，旁边数值保留真实幅度，绝不修改原指令。

`control_status.json`低频保存末端、两路命令、回执及显示耗时的最新快照；不是训练数据或完整指令录制。
独立诊断表也监测该显示进程的心跳和输出频率。

## 参数、文件和复验

```bash
# 不显示三维模型（无需模型资产）
bash scripts/view_grid_observation_live_v2.sh --model-mode none --hz 10
# 不启动RViz，运行15秒后退出
bash scripts/view_grid_observation_live_v2.sh --no-rviz --duration 15
# 较小显示器；默认布局针对本机高分辨率屏幕，可拖动面板
bash scripts/view_grid_observation_live_v2.sh --window-size 1800 1000
```

默认创建 `local/grid_live_v2/session-*`，保存 `live.rviz`、`session.json`、独立进程日志、
`processes.json` 和低频 `status.json`。显式 `--output NEW_DIRECTORY` 要求新目录。
JSON另含绘图累计最大耗时、最近128次绘图的P95、publish耗时及被最新输入覆盖的条数；首帧导入开销也计入。
不逐帧写PNG，也不保存原始传感器流。`status.json`与`control_status.json`退出后是历史快照，应结合时间与进程状态。
单个派生图进程退出时其他面板继续运行，并在终端及诊断表显示故障；不自动重启失败worker。
独立探针、诊断核心退出时整套查看器退出，避免留下无法更新的健康表；本机仍需观察系统负载。

依赖沿用原版：ROS Jazzy、RViz、NumPy/Pillow/PyYAML与项目Python依赖；三维显示另需模型和匹配的现场marvin_msgs。
左侧Displays/Views默认隐藏，给图像和三维区域留空间；可通过RViz的Panels菜单重新打开。
不需要新装PyQt运行查看器。开发工具 `build_grid_live_v2_layout.py` 重生成布局时才需PyQt5。

无硬件验收命令（使用200..232测试domain，拒绝domain13；测试源发布合成图像、EEF、控制消息及回执，无真实执行器）：

```bash
source /opt/ros/jazzy/setup.bash
source local/live_feedback_ws/install/local_setup.bash
PYTHONPATH="src:ros2/omi_sensors:$PYTHONPATH" local/venvs/daimon312/bin/python \
  scripts/check_grid_live_v2.py --output local/diagnostics/新的v2检查目录
# 可追加 --gui --model 检查实际RViz窗口与三维显示
```

该工具检查坏字段、单worker暂停/退出、单源断流、参数查询、两路指令／EEF数值与失效状态，
以及其他面板持续更新、查看器没有控制publisher和退出无残留。只读订阅也会让控制topic出现在ROS图中，
因此以publisher归属判定有没有发控制，不能仅检查topic是否存在。
它不替代真实传感器长期性能、跨机时钟同步或曝光到屏幕延迟验收。
