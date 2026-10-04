# 手柄末端控制与 SDK 坐标适配：开发记录

## 当前结论与范围

手柄六维增量控制、RB 人工接管选择、直接 ROS 发布、可配置 SDK 输出 wrapper，以及转换前后显示已实现。
用户已现场运行早期直接控制程序，并反馈右摇杆向左导致上下移动；换轴版本的实际方向尚未验收。
助手只运行离线测试、无动作发布预览及隔离测试话题，不曾启动现场机械臂动作发布。
当前 shadow 模型未接候选发布者，真机 RL transition/奖励/经验池闭环未完成。

操作教程：[gamepad_control.md](../../../../tutorials/gamepad_control.md)。
分阶段记录：[2026-10-04 编年](../chronicles/2026-10-04-gamepad-intervention.md)。
开发前检查点：`oct_03_branch`，`1a5f564`。用户随后要求提交当前进展，以下手柄代码与文档纳入本次进度提交；具体提交号见 git log。

## 需求与设计演进

1. 用户希望用手柄进行真机 RL 干预：按住 RB 接管、松开恢复策略；断连不能当作释放。
2. 布局最终确认：右摇杆平面移动、十字键上下升降、左摇杆两个倾斜轴、十字键左右绕 Z 旋转。
3. 首版独立节点完成手柄/候选动作选择，但现有 shadow 仍只读，因此没有有效候选时松开 RB 为零增量。
4. 用户要求仿照 Downloads 中最新 circle_test.py 直接发 topic，新增简单的 gamepad_test.py，独立于策略输入。
5. 用户反馈“向左”实际变成上下，检查所提供 SDK 压缩包，发现 BASE/TCP 模式、UserFrame 与 ABC 角语义。
6. 按用户提出的单臂安装方向假设增加输出 wrapper：换轴就是变量替换和改符号；多轴旋转另做旋转向量到 ABC 转换。
7. 用户只使用 --scale 启动，感觉没有区别，明确默认 legacy 不转换，需显式指定 --output-convention。
8. 用户要求显示原始值、是否转换、最终值，两个发布入口现均使用同采样的格式化输出；教程统一整理。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `scripts/gamepad_test.py` | 用户当前现场入口；--execute、--scale、预览/发布、RB 门控；不订阅策略 |
| `src/omi_hil_rl/real/linux_gamepad.py` | 非阻塞读取 Linux joystick，按 ioctl 轴/按钮语义映射识别，初始化事件及断连清理 |
| `src/omi_hil_rl/real/gamepad_control.py` | 原始六维映射、死区、合速度限制、单位接口和 Arbiter |
| `src/omi_hil_rl/real/sdk_action.py` | 输出模式、安装换轴、旋转向量转 ABC、共用终端输出格式 |
| `src/omi_hil_rl/real/gamepad_node.py` | 带策略候选输入的10Hz节点，--publish，动作来源与可选JSONL记录 |
| `tests/test_gamepad_control.py` | 六轴映射、组合速度、输入约束、接管/断连/候选生命周期 |
| `tests/test_gamepad_test.py` | 直接入口门控、scale/频率、输出wrapper、同采样显示与转换标记 |
| `tests/test_sdk_action.py` | 安装变换、正负单轴、合成旋转等价性、欧拉奇异情况及非法输入 |

## 操作空间和发送协议

内部六维动作：`[dx,dy,dz,rx,ry,rz]`，位置 m、旋转向量 rad，以固定操作坐标系 X前/Y左/Z上表达。
这不是绝对位姿，也不是未经积分的速度。程序把速度配置除以频率生成每步增量。

| 操作（均按住 RB） | 转换前动作 |
| --- | --- |
| 右摇杆前/后 | +X/-X |
| 右摇杆左/右 | +Y/-Y |
| 十字键上/下 | +Z/-Z |
| 左摇杆右/左 | +Rx/-Rx |
| 左摇杆前/后 | +Ry/-Ry |
| 十字键左/右 | +Rz/-Rz |

默认10Hz，10mm/s、10degree/s，死区0.15；平移、旋转分别限制向量模长，组合输入不会放大合速度。
直接入口 --scale 同时乘两种速度；scale=0.5 对应5mm/s、5degree/s。
--signs 作用于转换前手柄动作，不用于再次补偿已配置的安装换轴。夹爪和其余按键未接入。

最终 topic `/omi/action/decision`，Float64MultiArray，空 layout，六维 mm/degree。
不包含左右臂字段或 frame_id，由接收端选择机械臂并理解协议。
原始参考是 `/home/zhoutong/Downloads/oct04/robot_pose/circle_test.py`：该最新版默认预览、--execute后确认发送。
不可与仓库旧版 scripts/circle_test.py 的默认话题/启动方式混为一谈，也未覆盖用户的 Downloads 文件。

## SDK 调查及转换规则

用户提供 `/home/zhoutong/Downloads/oct04/sdk_python/SDK_PYTHON.zip`。
已直接读取归档中的 `fx_tcp_force.py:360–398` 与 `docs_1003_delta_IK.md`，没有运行其机器人控制接口。

函数 `solve_tcp_delta_ik(current_joints, delta_trans_mm, delta_rot_deg, frame)`：

- frame=0/FRAME_BASE：`p'=p+Δp`，`R'=ΔR R`。
- frame=1/FRAME_TCP：`p'=p+RΔp`，`R'=RΔR`。
- SDK 旋转增量为 ABC degree，`ΔR=Rz(C)Ry(B)Rx(A)`，不是旋转向量。
- 非单位 UserFrame 会影响 FK/IK 表达系；函数不会自行清除 UserFrame。
- 单臂安装 Base 与操作坐标系相同与否仍需标定；TCP 参数实际取值未知。

因此旧现象可能来自 TCP 模式、安装旋转、UserFrame 或接收端重排；未取得接收代码，不能断定唯一原因。

安装预设假设 SDK +X向前、+Z向左、+Y向下：

```text
R_B_from_O = [[1,0,0],[0,0,-1],[0,1,0]]
(dx,dy,dz) -> (dx,-dz,dy)
(rx,ry,rz) -> (rx,-rz,ry)  # 此处仍是旋转向量
```

实现用分量替换。旋转随后通过旋转矩阵提取 SDK ABC；多轴时不能只交换欧拉角分量。
同一个 TCP 点的位移不需要加基座原点间平移；左右臂分别核对安装变换。

输出模式：

| 模式 | 行为 |
| --- | --- |
| legacy（默认） | 不换轴，旋转向量以degree发送，保持旧版行为 |
| sdk-base-aligned | 不换轴，旋转向量转 SDK ABC |
| sdk-x-forward-z-left | 安装换轴，再转 SDK ABC |

两个发布入口在最终动作选定后调用同一个 wrapper，避免人工和策略使用不同协议。
接收端必须使用 FRAME_BASE 并核对 UserFrame；本地 wrapper 不会改变远端调用设置。
安装预设是待验证假设，不是校准结果。

## 控制与显示行为

直接入口：RB松开/断连发送零增量；持续按住且有输入则持续移动，不订阅任何策略候选。
策略入口：RB按住时完整覆盖策略，回中也不归还；释放后清空旧候选，等待观测时间晚于释放检测时刻的新候选。
候选输入 TwistStamped 的 linear/angular 实际承载每步 m/rad 增量，frame_id默认base。
候选最大年龄0.2s，拒绝未来、重复/倒序、非有限、超单步范围；每个候选最多使用一次。

终端原始值来自同次采样、死区/scale/符号/RB处理后、wrapper之前，以mm/旋转向量degree显示。
最终值就是交给publisher的数据；SDK模式显示mm/ABC degree。显示做精度格式化，消息不做显示舍入。
显式展示转换启用/模式、换轴、转ABC，以及“仅预览”/“已发布”；操作已应用但数值相同仍标记转换是。
直接入口约2Hz打印、策略入口约1Hz打印，状态变化立即打印；动作默认10Hz。
可选JSONL仅在策略入口提供，字段和命令详见教程，不等于实测轨迹。

## 验证与边界

最近测试命令：

```bash
source scripts/env.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_sdk_action.py tests/test_gamepad_control.py tests/test_gamepad_test.py --tb=short
```

结果67项通过，非全仓库结果。本次文档整理不重复运行未改变的代码测试。
原始首轮相关回归37通过1跳过、SDK wrapper阶段63通过，均为历史阶段测试结果。
已识别本机Xbox设备/dev/input/js0，验证无动作发布预览；早期隔离domain113测试话题收到了六维零增量、空layout，并验证Ctrl+C正常退出。
新显示的实际预览检查通过。未验证换轴后的真机运动方向、旋转、多进程策略恢复或训练闭环。

程序没有位姿反馈/工作空间/累计位移限制。停止发布或零增量不等于硬件急停，接收端需处理断流。
同话题多publisher检测属于运行期检测，不是跨进程锁；部署时仍需避免多个控制源。

## 继续工作顺序

1. 获取远端接收回调与SDK初始化，确认frame、UserFrame、单位、关节角单位、TCP定义及左右臂选择。
2. 退出旧进程，带转换参数启动预览，逐轴核对原始/最终值。
3. 用户现场用右臂低速逐轴验证平移，再验证旋转；记录方向和现象，不把假设矩阵直接当事实。
4. 再测松RB/断连/退出，并核对设备端响应。
5. 坐标语义确认后才接正式策略producer；再接真机transition与训练。左臂迁移单独核对变换。

当前工作区还有grid_live_review相关代码/测试/教程的其他改动，不属于本手柄功能，勿覆盖、回滚或误记为本次成果。

## 当前进度提交验证

用户授权提交整个当前工作区进展，同时保留实时看板的独立刷新/显示偏移改动。
在 ROS 环境运行手柄三组测试和 test_grid_live_review.py，合计73项通过；git diff --check通过。
该检查不构成换轴后的真机验收。系统/tmp交接文件不属于仓库提交内容。
