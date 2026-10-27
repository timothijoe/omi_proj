> 历史资料：原路径 `docs/agent/hardware/chronicles/2026-10-17-spacepilot-control.md`；2026-10-26归档。正文中的运行状态和参数只适用于原记录时期。
> 当前说明见[模块入口](../../../../../modules/teleoperation.md)；本页保留原过程与证据。

# 2026-10-17 SpacePilot 映射到手动控制话题

用户要求将已纳入项目的3D鼠标按现有手柄命令的方式发送六维末端增量，并补充平移、旋转各自可调的 scale。

新增 `scripts/spacepilot_test.py` 与 `real/spacepilot_control.py`，复用已确认的输入方向、现有 SDK 输出转换和接收端自动路由。默认10 Hz、基础速度10 mm/s和10°/s；增加 `--translation-scale`、`--rotation-scale`，同时保留公共 `--scale`，均允许0禁用。默认实体3按住启用，命令行提供 toggle 和轴模式选择；未绑定夹爪或回位。

SpaceNav 增加可选 reset 回调，输入断连/设备变更时撤销启用。预检增加按需检查发送频率及 base 坐标模式。原有 SpacePilot GUI、手柄入口和已迁入的 AprilTag 文件保持各自用途。

首轮相关离线检查：84 tests passed、6 subtests passed，涵盖新增控制测试、原 SpacePilot、SDK 转换、接收端预检及手柄映射。`--help` 已实际核对。只读预览使用平移0.5/旋转0.2倍率，验证真实驱动连接及 SIGINT 正常退出；没有启动 ROS 发布者或发出机器人动作。运行方法与后续真机验收边界见[教程](../../../../../../tutorials/spacepilot_control.md)及[当前实现](../evolution/spacepilot-control.md)。

## 同日现场反馈：实体3上报 ID19

用户运行预览后反馈：按住实体3没有启用，实际日志显示按钮 ID19。初版沿用旧 GUI 记录的 ID14，与本次设备输入不符。控制入口及 EnableGate 的默认值统一改为19，保留 `--enable-button` 覆盖；未修改 GUI 模式键或启停语义。补充回归验证默认19按下启用/松开停止、14不会误启用，以及显式指定14仍有效；既有模拟发布测试使用19。本轮未运行机器人，按键物理对应依据用户报告。

## 同日现场反馈：接收端网络发现

用户执行入口后报参数服务不可用，设 domain13 后仍失败。本机进程中没有接收端；只读探测在 domain13/LOCALHOST 下无服务，切 SUBNET 后立即发现服务。参数为 `/omi/action/decision`、`/omi/controller_test/decision`、10 Hz、base，connect_on_start/motion_authorized 均 true；这些是配置读数，不是物理状态证明。

进一步预检发现：两路订阅可见且为 Float64MultiArray，但节点名和命名空间分别为 `_NODE_NAME_UNKNOWN_` / `_NODE_NAMESPACE_UNKNOWN_`。新 SpacePilot 入口增加可选的唯一匿名端点匹配，并保留参数服务、连接配置、频率、坐标与话题类型检查；其他入口默认严格节点身份检查不变。完整网络只读预检随后成功，未启动动作发布者。

相关预检、SpacePilot、手柄及 async_training 回归共71项通过。教程改用本次实测可用的 SUBNET 设置，保留本机独立部署说明。没有重启或修改机器人接收端，也没有发送运动指令。

## 同日现场反馈：平移方向疑似合并

用户报告前后、左右、上下输入似乎都使机械臂上下运动。静态转换为可逆轴排列，本机 libspnav 只读配置返回 axis_map=[0,1,2,3,4,5]、axis_sensitivity全1、invert=0、swap_yz=0、button19_action=0。ctypes Motion 字段布局与[上游头文件](https://raw.githubusercontent.com/FreeSpacenav/libspnav/master/src/spnav.h)一致；这些检查不能替代实际设备输入/指令/机械臂反馈对照。

新增原始输入诊断 `--debug-input`，SpaceNav保留设备六轴快照，断连/设备变更/过期时一并归零；没有改变方向转换或控制参数。补充 ctypes 事件解析测试，三轴样本保持独立，相关测试57项和6个subtest通过。已请求用户提供前推、左推、上提三组无执行预览，原因仍待定位；本轮未发布机器人动作。

## 用户三方向预览结果

用户按前推、左推、上提顺序操作两轮，使用 translation、dominant-axis、translation-scale=0.5、rotation-scale=0。代表样本如下；所有日志均为“仅预览”，不能充当已发布topic或真实位移证据。

| 方向 | 设备原始 x/y/z/rx/ry/rz | 最终 SDK 六维增量（mm/ABC度） |
| --- | --- | --- |
| 前推 | [-52,-75,293,-257,0,-5] | [0.414157,0,0,0,0,0] |
| 左推 | [-225,-13,0,0,0,-270] | [0,0,0.311747,0,0,0] |
| 上提 | [-21,207,0,-43,-19,-4] | [0,-0.284639,0,0,0,0] |

用当前代码离线重放上述样本，与日志一致，三个平移轴独立。相同样本按此前 all 模式、rotation-scale=0.2计算，前推产生 SDK dC≈0.143976°，左推产生 dA≈-0.151807°；说明未禁用旋转时会有旋转混入，但不能据此认定原真机异常只由此造成。下一步对照纯平移单轴条件下的实际命令与机械臂运动；不调整轴映射，不自动发送真机指令。

## 再次预检报错后的状态复核

用户用 translation-scale=1、rotation-scale=0.054、translation模式启动时再次报服务不可用；日志表明localhost已关闭，但未显示domain。随后独立以domain13/SUBNET进行服务读取及项目完整预检均通过，接收端仍为10 Hz/base，完整预检此时已可辨认订阅节点名。无法由后续成功证明用户失败时的具体原因，保留终端环境差异或发现瞬时不可用的可能。

为减少盲查，发送入口启动和服务不可用错误新增 ROS_DOMAIN_ID、ROS_LOCALHOST_ONLY、ROS_AUTOMATIC_DISCOVERY_RANGE、RMW_IMPLEMENTATION 的定向显示；不修改用户环境、不改变预检或自动重启接收端。建议用命令前缀固定13/0/SUBNET重试。translation模式仍屏蔽全部旋转，非零rotation-scale并不会开启旋转。本轮只读检查，没有发送动作。

## 首次有效动作立即发送

用户反馈起动有滞后，并明确要求首条有效动作立即发送、持续保持10 Hz，速度和映射不变。修改 `scripts/spacepilot_test.py` 的发送条件：零/非零状态发生变化时立即发送，持续非零时保持原截止时刻节流。每次实际发送后按原周期重新设置截止时间；动作换算、scale、频率参数及接收端均未修改。

新增模拟时钟+假ROS发布测试：10.00秒已发静止零指令后，10.01秒首次有效动作同轮发出；持续运动换方向不会额外加速发布，但到期发送最新方向；10.14秒松键/回中/输入过期立即发零，10.15秒再次有效动作立即发送，随后恢复100–110 ms发送间隔（含模拟10 ms轮询离散误差）。三种停止原因均覆盖，原有断连/异常测试保留。

验证命令：`PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_spacepilot_control.py tests/test_spacepilot_pose.py tests/test_sdk_action.py`，60 passed、6 subtests passed。未运行真机发送，未测端到端时延。退出旧发送程序并以原命令重启生效，无需重建接收端。

## 首条立即发送后仍有迟滞：只读初查

用户继续反馈SpacePilot体感比手柄迟滞。核对正在运行的发送进程，启动时间晚于入口文件修改时间，已排除该进程未重启加载首条立即发送修改这一解释。未停止或更改用户进程。

并行只读检查：独立驱动连接6秒共595次poll，P50约0.012 ms、P95约0.027 ms、最大0.258 ms；含设备名称查询的6次poll最大也为0.258 ms。轮询间隔P50约10.074 ms、P95约10.198 ms、最大10.601 ms。该窗口motion_events=0、button_events=0。

另用ROS只读订阅手动topic约7秒，收到68条且全部为零；接收间隔中位数103.213 ms、P95约104.205 ms、最大104.722 ms。独立观察节点执行两次count_publishers的耗时中位数约0.024 ms、最大0.064 ms。

这些数据仅说明本轮空闲时输入读取、图查询及零指令节拍没有明显阻塞，不能推导动作时的端到端延迟或真机反馈延迟。发送链没有使用GUI的位姿积分，仍直接映射旋钮输入；需结合用户确认的起动/转向/停止迟滞类别继续定位。没有调整速度、10 Hz发送频率或接收端参数，也没有从诊断程序发布任何动作。

## 起动/停止迟滞细分与由用户启动的输入采样

用户确认起动和停止特别明显，随后描述为“松开按钮，但实体3还在按动”；本轮按松开中间旋钮、仍按住实体3理解，继续排查旋钮回中后的残余输入。40秒只读采样未收到运动或按键事件，产物 `local/spacepilot/latency/20261017_165258_readonly.json` 不可作为运动时延证据。

为避免交互采样窗口错过，新增 `scripts/spacepilot_input_check.py`，由用户按回车开始30秒采样，保存六轴、按键、本机单调接收时间、候选和状态转换。此入口无ROS初始化/发布路径。`--help`、0.1秒真实驱动只读运行、JSON契约和退出检查通过；测试样本运动/按键事件仍为0，待用户实际操作。

另外核对本地接收端：普通手动零只设置零速度及 `have_goal=false`，而 `_apply_guard_hold` 才会用当前关节反馈替换旧目标。停止增加目标不等于立即物理制动，现场接收端版本、目标跟踪及其与迟滞的关系尚未验证。未修改接收端、死区、速度、频率或输出映射，也未自动发送动作。

## 两发送端对照与共同执行链排查

用户要求对照发送方式，随后实测反馈手柄也有相近迟滞。检查两脚本：同一Float64MultiArray消息、depth1发布、接收端手动路由和SDK换轴；区别在输入采样、死区、手柄Z/Rz十字键离散输入及SpacePilot首条/零指令立即发送。使用假ROS、假设备和模拟时钟调用两脚本实际循环：t=0.03起动、t=0.24回中，手柄t=0.10开始/t=0.30发零，SpacePilot t=0.03开始/t=0.24发零；没有真实ROS发布者。匹配速度和死区后1000组输入最终wire最大绝对差4.44e-16。结果保存在 `local/spacepilot/latency/sender_comparison_20261017.json`，不是实测端到端时延。

据用户新增对照转向共同接收端。只读读取现场参数：start_mode=3，K=[6,6,6,5,3,3,2]，D均0.3，ctrl_rate=200、manual_command_rate=10、manual_timeout=0.25、base、eef_publish_rate=50。12次参数服务往返中位数0.634 ms、最大0.756 ms；130组EEF接收间隔中位数19.979 ms、最大20.472 ms。这是短时网络与话题检查，不能排除运动时的阻塞或SDK反馈陈旧。

## 用户动作前准备：只读指令/反馈记录器

用户询问需配合什么操作，准备独立 `record_control_response.py/.sh`，不修改接收端执行逻辑。默认首条非零指令触发45秒记录，保留前2秒，收集manual command、joint_feedback、eef_left、receipt、接收端WARN以上rosout与参数快照。没有SDK加载和动作发布路径。这个记录只能衡量本机接收到的动作边界与反馈变化，尚不能替代SDK内部目标/发送时间记录。

Shell语法、Python入口、真实1秒immediate只读检查通过，获得当前200 Hz/base/模式3参数及关节、EEF各2条记录，JSON契约核对通过。产物 `local/diagnostics/control_response/20261017_172659_745587.json` 为静止入口验证，不是运动响应证据。建议先由用户用手柄做短前推、回中保持RB、再松RB的三次对照；自动采样避免先前输入检查未收到动作的时间窗口问题。

本地源码发现共同待测点：目标从上一SDK目标累加、零指令不替换最后SDK目标、模式3启动调用速度/加速度比例10/10、默认单线程串行运行控制及反馈回调。动作订阅源码为depth1；跨机图返回depth0不解释为现场真实队列配置。尚未测到命令回调到SDK下发及实测反馈的时差，未确认现场代码哈希，不宣称已找到根因。本轮只修正源码中“零指令立即停止”的误导性注释为“停止新增目标”，没有改变执行逻辑、启动模式、K/D或速度比，也未部署/重启接收端。另询问用户观察本体还是显示画面，以区分显示延迟。

## 19:32运动记录与最终文档/提交准备

随后核对本机500 Hz安装副本：执行逻辑与源码一致，仅停止语义注释有差别；该进程日志累计六次SDK_REJECTED，均带clear_set_return=0。静态检查实际libMarvinSDK.so并对照工作区参考SDK源码，OnClearSet在发送状态50/100返回false，表明此类日志涉及SDK本地发送忙，不等于控制器因目标超限拒绝。接收端仍存在未按clear_set失败分支退出、未检查send_cmd返回值便推进cur_joints的缺口，本轮没有修复或改控制参数。

用户提供 `local/diagnostics/control_response/20261017_193243_851241.json`：29.645秒，313条动作、1489条关节、1488条EEF；interrupted为提前结束，不是记录错误。当前200 Hz/模式3，四段全零后约0.22–0.30秒近停，继续X移动0.44–0.92 mm；起动到0.1 mm阈值约0.24–0.41秒。对应接收端日志无已记录WARN/ERROR/SDK_REJECTED，不能代表未记录的send_cmd从不失败。

数据、定义、原始哈希、速度超调迹象、两种停止时间口径和限制统一保存在[开发快照](../../../../cross-cutting/records/oct17_development_checkpoint.md)与[证据目录](../../../../../evidence/control_response_20261017/README.md)。新增可复现离线分析CLI，保留原始local文件不变。用户反馈比之前稍好，尚无受控A/B结论。按用户要求先写Markdown并准备本地提交，暂不调整阻抗、刚度、速度或停止策略。
