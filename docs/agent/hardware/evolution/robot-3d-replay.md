# 机器人3D录包回放

旧包独立入口 `scripts/view_observation_robot_3d_bag.sh`，默认localhost domain96。
复用原图像回放与文字看板，在RViz中央显示随历史关节反馈变化的双臂网格；
右侧Image面板显示视觉/触觉/机器人数值，左侧保留显示控制项。
用法和依赖见[教程](../../../../tutorials/robot_3d_replay.md)。

## 实现与数据边界

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
绘图固定step16、scale20、deadband.01、max24，红色表示截断；与旧重建看板scale2、
deadband.2不同。深度固定显示0..0.3原始单位。单位/力标定、SDK版本与基准未确认。

### 当前关键问题：坐标与触觉幅值

**小坐标轴来自录包末端数值，但在机器人模型中的落点尚未验证，不能当作正确TCP。**
用户暂定该末端为抓取中心；现实现仅暂假定base_link=model robot_base。
约8秒样本的记录末端与模型left_link7相差[0.23258,-0.02790,0.90322]，按米解释约0.933米；
连杆轴与末端轴差角接近180度。模型基座在world中的0.3米抬高已在比较中扣除。
不是已标定工具偏移，也不能仅以时间差解释；尚未实施坐标修复或人为平移。
需要源发布代码、实际运动学模型、关节约定、基座定义及法兰到抓取中心变换。
原包无TF，当前已检查的参考代码未找到eef_left发布实现。

原生触觉波动与旧重建版明显不同是用户观察，尚无受控等价性比较。
需用同一新包、匹配基准和算法输入、统一显示参数，比较向量数值及时间序列；
不能凭箭头短判断数据有错。当前数值场约11–12 Hz、偶发0.26–0.37秒间隙，
10 Hz看板还会跳过部分源帧，不能用于证明已保留所有瞬态。
各路有时间戳不代表已验证同源采样时钟；SDK帧号可辅助但非强制要求。

### 验证、依赖与后续

全套120 passed、5 skipped；实包及GUI检查证明图像、运动、循环、模型描述、末端三轴可见，
没有控制topic。不证明现场FK、Humble、30 Hz吞吐或训练闭环。
细节及录包完整性见[本阶段编年](../chronicles/2026-10-02-native-record-review.md)。
额外准备匹配Marvin消息源码并重建、原包ZIP/目录、robot_assets与相邻MarvinCCS；
安装ROS/Jazzy、robot_state_publisher、Pillow/NumPy/SciPy/PyYAML/zstd。
自动读取本机local/robot_state/viewer.env；新入口不需要触觉SDK/零载荷基准或硬件连接。
资源及缓存不进Git，换机重新生成缓存/URDF，详见[拷贝清单](../../../../tutorials/machine_transfer_checklist.md)。
先小规模低速试采可以启动数据管线验证，尚需确定采样时间语义和动作标签，
不等于已有正式训练数据或策略验收；夹爪开合暂按用户要求排除。
