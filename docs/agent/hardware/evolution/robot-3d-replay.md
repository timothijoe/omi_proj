# 机器人3D录包回放

2026-10-09 存储更新：三份代表 bag 本体仍在本机；`local/bags` 及 `recorded_review`、
`wrist_recorded_review`、`grid_recorded_review`、`tactile/replay_cache` 已迁入
`omi_proj_data/local/`，原目录软链接兼容。现有录包回放入口需要挂载移动盘；
现场实时看板不使用这些录包缓存。SDK/基准/本机模型资产保留。
范围和最终状态见[存储契约](../../interfaces/local-storage.md)。

## 当前代表录包与操作入口（2026-10-07）

历代录包回放现统一从[三包 RViz 操作页](../../../../tutorials/rviz_representative_bags.md)选择完整命令：旧 record010 使用 `/home/zhoutong/omi_folder/representative_rosbag/october/record010/bag_001/`，原生触觉、腕部与 Stand/Hybrid 对照使用同目录 `native_wrist_bag_004.zip`，24×16 grid 回放使用 `grid24x16_bag_001.zip`。本机旧 Downloads 路径仅为兼容链接；新文档和人工启动应使用上述真实路径。Stand/Hybrid 另需 `/home/zhoutong/Downloads/oct2/Marvin_Stand_2026.2.2.rar`，旧重建看板另需零载荷基准和 Daimon SDK。

这三种包覆盖现有**录包驱动**的主要 RViz 版本；实时看板读取现场话题，不使用代表包。其他历史录包归档于 `/media/zhoutong/zt-think-d1/omi_rviz_archive_20261007/`，位置和校验见[本次编年](../chronicles/2026-10-07-rviz-bag-relocation.md)。下文的 record001/record010 实验数字仍指当时使用的原包，不改写为本次三包的测试结果。

当前两路相机裁剪以[ROI第一版](../../../design/camera-roi-v1.md)为文字基线，
记录外部/腕部的固定框及插值区别。bag_004腕部近乎静止问题已定位到录包内容层，
未发现缓存或发布取帧错误；怀疑现场采集，但根因未确定，按用户要求暂缓。
不能再以“像素哈希不同”宣称画面运动正常。证据见
[腕部ROI与采集遗留编年](../chronicles/2026-10-03-wrist-roi-and-capture-followup.md)。

## 入口选择与当前结论

针对oct03的bag_004，新增`view_wrist_observation_3d.sh BAG [RATE] [--no-rviz]`，domain93，
直接使用命名修正版模型而不是RAR。右上腕部原图和旧版ROI的128预览，右下触觉raw；
现已复用旧看板中心(.500,.704)/短边比例.36与Lanczos缩放，v2缓存替换初版中心大方框，
1920×1080输入的裁剪为(766,566,389,389)。单元测试与旧看板128结果逐像素相等。
旧入口默认行为不变，共享缓存函数仅新增显式可选topic/render/version参数。
bag_004有腕部图像/内参，旧record001缺失结论不变。
ROI已按第一版记录；独立[EEF v2策略](../../training/evolution/eef-action-space.md#v2可选腕部相机与输入源标记)
已接可选腕部，使用最近邻训练预处理，不改变本看板。
见[独立教程](../../../../tutorials/wrist_bag_review.md)。

当前继续核查record001机器人姿态时，优先使用**Stand方向修正版**，不替换旧稳定入口。
它是相对旧回放角度约定的派生模型，不是已确认厂商模型错误或已完成真机标定。

| 入口脚本（均在scripts/） | 默认domain | 模型及用途 |
| --- | --- | --- |
| `view_corrected_stand_observation_3d.sh` | 94 | 当前推荐对照：新Stand完整外观/高度＋关节方向修正 |
| `view_hybrid_observation_3d.sh` | 95 | 保留旧链，部分新外观；历史对照，不修复高度差 |
| `view_observation_robot_3d_bag.sh` | 96 | 旧record010数据与重建触觉的稳定机器人看板 |
| `view_recorded_observation_3d.sh` | 97 | record001原生字段＋旧MJCF模型，保留约0.93米旧偏差 |
| `view_stand_observation_3d.sh` | 98 | 新Stand原角度定义；直接套录包姿态不匹配，仅供对照 |

所有入口仅显示历史数据，不发布实际控制指令。domain94～98是不同试验入口，
不是一个入口自动选择的不同模式；不要在同一domain重复启动同一入口。

## Stand方向修正版（2026-10-03）

固定命名归档：`local/models/omi_marvin_stand_axis_corrected_v1/urdf/omi_marvin_stand_axis_corrected_v1.urdf`。
这是OMI派生版，不是厂商原版；原版另存于同目录`source/`，网格存`meshes/`，
修改和来源哈希见`README.md`与`provenance.json`。整个资源包Git忽略，搬迁须另拷贝。
当前脚本仍由RAR生成运行配置，不自动加载命名归档。形成过程见
[本阶段编年](../chronicles/2026-10-03-stand-axis-correction.md)。

新独立入口`view_corrected_stand_observation_3d.sh`使用domain94。新URDF相对旧回放约定：
左3/4/6、右3/4/5关节方向相反。派生URDF只改axis及配套限位符号，不改origin、
mesh或录包角度。每侧300随机角度的模型等价性验证通过；保留新肩部高度后，
录包EEF与L7位置差呈近乎恒定的局部约23.3厘米偏移，而非旧版约90厘米高度差。
这支持工具变换假设，不构成TCP标定；左joint4机械限位仍与录包不一致。
134测试通过、5跳过，已启动RViz并检查截图。定量依据与警告见
[方向修正版教程](../../../../tutorials/corrected_stand_review.md)。

## Hybrid 对照（2026-10-03）

用户反馈直接套新Stand URDF的姿态不对，改为独立
`scripts/view_hybrid_observation_3d.sh`（localhost domain95）。旧运动链的14个活动关节
与root固定变换逐项比较完全不变；只配准visual网格，不修改关节角、轴或零位。
两侧1～4、6使用新网格，5、7回退旧网格；支架外观做高度平移，安装宽度未标定。
133测试通过、5跳过；真实模型15个joint属性与子元素逐项一致。
外观拟合非运动学标定，EEF差异未解决；详见[教程](../../../../tutorials/hybrid_urdf_review.md)。

## Stand URDF 独立对照入口（2026-10-03）

`scripts/view_stand_observation_3d.sh BAG MODEL.rar` 使用新 Stand 模型，固定 localhost
domain98，旧入口与旧模型转换代码不变。读取归档中的 URDF/STL 到忽略的 local 目录，
保留关节运动学，仅映射名称、mesh 路径并移除游离文本；原始文件保留。
世界到新模型根坐标系为单位变换，录包 base_link 暂对应 ZJ_Robot_link，未经校准。
单独显示左 L7 原点标签和坐标轴，不冒称法兰/TCP，不猜测工具偏移。

已通过132项测试、5项跳过；实际启动 robot_state_publisher 与 RViz，ROS 订阅检查收到
14关节、14动态TF、1536×1170面板与两类marker，域内没有 `/tj/control/` topic。
GUI进程启动不等于人工视觉验收；模型基座/关节映射及抓取中心仍待核对。
操作与资源依赖见[独立教程](../../../../tutorials/stand_urdf_review.md)。

## 旧record010模型与入口（仍保留）

旧包独立入口 `scripts/view_observation_robot_3d_bag.sh`，默认localhost domain96。
复用原图像回放与文字看板，在RViz中央显示随历史关节反馈变化的双臂网格；
右侧Image面板显示视觉/触觉/机器人数值，左侧保留显示控制项。
用法和依赖见[教程](../../../../tutorials/robot_3d_replay.md)。

## 旧record010入口的实现与数据边界

`real/robot_replay_3d.py`从项目local/assets里的显式MJCF双臂链生成可视化URDF，
保留根基座、左右各7关节和原mesh位姿，拒绝不支持的关节/变换；
不引入原场景刀具、灵巧手、道具或动力学控制器。
因此显示到末端连杆，不含现场触觉夹爪模型、手指开合、头/躯干运动或精确工具TCP。
URDF与mesh来源记录在local生成目录；不能将本机路径生成物直接作为跨机器资产。

Marvin反馈数组按消息定义L1..L7,R1..R7映射，暂按rad解释，现场零点/方向/单位尚未标定。
关节目标命令不用于驱动模型。模型越限不裁剪原反馈，只在status报告警告。
数值正运动学与原MuJoCo模型对照一致，仅证明转换正确，不证明模型匹配现场。

机器人时间线从源包离线读取，不发布原控制topic。参考时间来自文字看板的历史header；
按参考取最近过去反馈，和原看板各相机/触觉并非曝光精确同步。
`/omi/replay_3d/joint_states`和独立TF只用于RViz；显示时钟使用当前时间，
原录包时间、滞后、来源和有效性保留在status，避免循环回放TF倒退。
缺反馈不伪造零位；暂停/失效时状态明确提示，旧姿态可保持显示。

## 验证与下一步

测试涵盖四元数转换、14轴链/资源、FK对照、历史取样、重复header暂停、循环和模型限位。
`scripts/check_robot_3d_replay.py`提供隔离域回放检查，可选 `--gui` 实际打开RViz并截图。
record010已检查模型描述、静态/动态TF、关节变化、循环、合并看板、无控制topic及无全局joint_states。
旧8个冻结看板文件不变。具体本轮证据见[编年](../chronicles/2026-10-02-robot-3d-replay.md)。

后续若需要准确夹爪/TCP显示，必须先取得正确模型、工具偏移与现场标定，不能把旧刀具/灵巧手代用。

## 新录包原生触觉与末端同屏

新入口 `scripts/view_recorded_observation_3d.sh ZIP_OR_BAG [RATE] [--no-rviz]`，
默认localhost domain97，独立于旧看板及schema2 SDK看板；当前只在Jazzy验证。
离线白名单读取外部彩色、两侧raw/deformation/shear/depth/force、关节反馈与eef_left。
按接收顺序缓存10 Hz图像和状态，逐字段显示源header年龄（250ms后STALE），
发布显示专用dashboard、末端MarkerArray、status和模型joint_states/TF，不发布控制topic。
显示时间用当前ROS时钟，历史时间另存header/status；不是训练对齐导出器。
新入口循环初始无反馈时使用零角占位、面板标WAITING；旧入口的缺反馈行为不变。

原生deformation/shear为288×384×2 float32，直接从Image/32FC2消息解码后画箭头，
不重新调用触觉SDK。raw为270×360；新增128×128触觉预览是直接缩放、改变宽高比，
不是定案的网络输入。相机128预览复用observation既有方形ROI。
当前右上角显示整图128预览再双线性插值放大到原图显示范围，右下角显示原raw；
不做新ROI或去畸变、不强制512显示。该缩放在离线缓存准备阶段完成，播放不增加重建计算；
缓存版本2与旧版分开，旧缓存保留。
**该布局只是当前实现，不是用户最终期望：右上角实际应为腕部相机原图与clip，
此前误将其理解成触觉预览。腕部需求尚未实现，见下方遗留项。**
绘图固定step16、scale20、deadband.01、max24，红色表示截断；与旧重建看板scale2、
deadband.2不同。深度固定显示0..0.3原始单位。单位/力标定、SDK版本与基准未确认。

### 当前关键问题：坐标与触觉幅值

**小坐标轴来自录包末端数值，但在机器人模型中的落点尚未验证，不能当作正确TCP。**
用户暂定该末端为抓取中心；现实现仅暂假定base_link=model robot_base。
在此domain97旧MJCF模型入口中，约8秒样本的记录末端与模型left_link7
相差[0.23258,-0.02790,0.90322]，按米解释约0.933米；
连杆轴与末端轴差角接近180度。模型基座在world中的0.3米抬高已在比较中扣除。
这不是已标定工具偏移，也不能仅以时间差解释。该旧入口保持不变；
新domain94入口已经修正角度约定并使用新Stand高度，剩余约23.3厘米局部偏移，
仍未确认物理TCP，不能把旧版0.933米差异当作新版结果。
需要源发布代码、实际运动学模型、关节约定、基座定义及法兰到抓取中心变换。
原包无TF，当前已检查的参考代码未找到eef_left发布实现。

原生触觉波动与旧重建版明显不同是用户观察，尚无受控等价性比较。
需用同一新包、匹配基准和算法输入、统一显示参数，比较向量数值及时间序列；
不能凭箭头短判断数据有错。当前数值场约11–12 Hz、偶发0.26–0.37秒间隙，
10 Hz看板还会跳过部分源帧，不能用于证明已保留所有瞬态。
各路有时间戳不代表已验证同源采样时钟；SDK帧号可辅助但非强制要求。

### 可视化遗留：右上角腕部相机原图与clip（待下一次处理）

议题状态（2026-10-03）：用户要求暂缓争论，保留核实项。
用户提供待核对的准确名称 `/tj/dm_camera/camera/color`；当前所检查的
oct2/record001.zip内metadata列出16个topic、21960条消息，未包含该名称。
这只说明当前文件的录包清单中没有它，不能证明设备端没有发布，亦不能代替其他包的检查。
后续与采集方对齐具体包版本/路径、实际发布名称和录包清单；在获得新证据前不推断原因，
不改topic映射或可视化代码。见[话题核查编年](../chronicles/2026-10-03-wrist-topic-question.md)。

最终需求：右上角显示夹爪附近另一颗腕部相机的原图和128预览放大图，
右下角显示A/B原始触觉；不强制512显示像素，rect不是去畸变。
腕部ROI坐标/裁剪或整图缩放方式需在取得真实图像后确认。
当前右上角触觉预览是需求误解产生的实现，不能作为腕部功能完成的证据。

新record001包无腕部图像：10个Image topic属于外部彩色、外部深度、
双侧raw/deformation/shear/depth共6类；旧 `/tj/dm_sensor/camera/color` 缺失，
没有其他腕部topic，也没有录制的128 clip。更换启动指令不能补出缺失数据。
下一步先向采集方核实启动与录包清单，取得含腕部图像的数据，再增加读取/缓存/布局；
无数据时须明确标缺失，不允许用触觉图或旧包不同步画面替代。
插值放大可低成本实现，但腕部端到端延迟尚未测量。用户明确暂缓到下一次修改，
本轮只记录遗留。澄清过程见[后续编年](../chronicles/2026-10-02-wrist-viewer-followup.md)。

### 验证、依赖与后续

全套120 passed、5 skipped；实包及GUI检查证明图像、运动、循环、模型描述、末端三轴可见，
没有控制topic。不证明现场FK、Humble、30 Hz吞吐或训练闭环。
后续触觉预览布局自动测试为121 passed、5 skipped，实际新版缓存PNG已检查，
未重新验收GUI；这些结果均不构成缺失腕部相机的显示验收。
细节及录包完整性见[本阶段编年](../chronicles/2026-10-02-native-record-review.md)。
额外准备匹配Marvin消息源码并重建、原包ZIP/目录、robot_assets与相邻MarvinCCS；
安装ROS/Jazzy、robot_state_publisher、Pillow/NumPy/SciPy/PyYAML/zstd。
自动读取本机local/robot_state/viewer.env；新入口不需要触觉SDK/零载荷基准或硬件连接。
资源及缓存不进Git，换机重新生成缓存/URDF，详见[拷贝清单](../../../../tutorials/machine_transfer_checklist.md)。
先小规模低速试采可以启动数据管线验证，尚需确定采样时间语义和动作标签，
不等于已有正式训练数据或策略验收；夹爪开合暂按用户要求排除。
