# 2026-10-04：手柄六维控制与 RB 接管首版

## 阶段结论

已实现手柄读取、六维动作映射、人工/策略动作选择及 ROS 发布入口。
已完成离线逻辑测试和本机手柄识别、ROS 无动作发布预览。
**尚未驱动真机验证，也未把现有 shadow 模型接成策略候选发布者；不是完整真机 RL 闭环完成。**

开发前基线为 `oct_03_branch` 上的 `1a5f564`，包含此前 51 个文件的进度快照。
该提交不包含本次新增的手柄实现；本次文档整理未另行提交代码。

## 用户确认的操作设计

| 输入 | 对应动作 |
| --- | --- |
| 右摇杆前后 | X 方向平移 |
| 右摇杆左右 | Y 方向平移 |
| 十字键上/下 | Z 方向升降 |
| 左摇杆左右 | 绕 X 轴倾斜 |
| 左摇杆前后 | 绕 Y 轴倾斜 |
| 十字键左/右 | 绕 Z 轴旋转 |
| 按住 RB | 人工完整覆盖策略动作 |
| 松开 RB | 等待新的有效策略候选，无候选时零增量 |

摇杆回中不释放人工接管。断连进入零增量状态，不视作 RB 松开；重连清除旧候选并重新读取按钮状态。
方向以固定基座坐标轴定义，+X 前、+Y 左、+Z 上是待现场核对的约定。
旋转采用基座系旋转向量，接收端的旋转定义和正负号仍需确认。夹爪暂未接入。

## 实现与接口

- `src/omi_hil_rl/real/gamepad_control.py`：死区、六维映射、组合速度限制、单位转换和动作选择。
- `src/omi_hil_rl/real/linux_gamepad.py`：非阻塞读取 Linux joystick，通过内核 axis/button map 识别语义，处理初始化事件与断连。
- `src/omi_hil_rl/real/gamepad_node.py`：独立 10 Hz 节点；默认仅预览，`--publish` 开启动作发布。
- `tests/test_gamepad_control.py`：映射、接管切换、断连、候选新鲜度与输入校验测试。

最终输出 `/omi/action/decision`，`std_msgs/msg/Float64MultiArray`，空 layout，顺序 `[dx,dy,dz,rx,ry,rz]`，单位 mm/degree。
消息没有左右臂标识，由接收端决定控制哪只机械臂。节点检测到其他同话题 publisher 时退出。
默认合平移速度 10 mm/s、合角速度 10 degree/s：每 0.1 s 最多 1 mm、1°；多轴组合不会增大合速度。
摇杆死区 0.15，支持速度、六轴符号和设备路径参数。

策略候选输入为 `/omi/policy/candidate`，`geometry_msgs/msg/TwistStamped`。
六个字段承载每步增量 m/rad，不是速度；默认 frame_id 为 `base`。
时间戳必须取该次推理观测的参考 ROS 时间。候选超过 0.2 s、未来时间、重复/倒序时间戳、非有限值、超单步范围均被拒绝。
候选最多使用一次，RB/连接状态变化时清除缓存；释放 RB 后只接受参考时间晚于释放检测时刻的候选。
可选 JSONL 记录选择来源、intervention、动作及是否发布，不代表反馈或实际已执行轨迹。

## 已完成验证

本阶段执行：

```bash
source scripts/env.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_gamepad_control.py tests/test_intervention.py \
  tests/test_executed_action_sac.py tests/test_eef_action.py --tb=short
```

结果 **37 passed, 1 skipped**，为上述相关测试集合，不是全仓库测试结果。
本机识别到 `Microsoft X-Box 360 pad`，设备 `/dev/input/js0`：
轴映射 `[0,1,2,3,4,5,16,17]`，按钮映射包含 RB 的 Linux 代码 `311`。
在 ROS domain 13 运行约 3 秒预览，正常显示 `paused_no_policy` 和六维零增量，无动作 publisher。
这仅验证设备读取和节点启动，不代表人工逐轴操作或真机轨迹验收。未执行 `--publish`。

## 下一步

1. 在预览模式逐轴操作，确认所有按钮、摇杆方向和 RB 状态；再用右臂低速确认基座轴、旋转语义及接收端响应。
2. 验证人工回中、松开 RB、拔出手柄和程序退出时的实际机械臂行为；零增量并不替代接收端断流停止机制。
3. 给正式策略实现独立候选发布者，再联调人工接管与释放后的策略恢复。当前 `stack_shadow` 继续只读，没有自动接通。
4. 真机 RL actor 根据最终选中动作和干预标记建立 transition，结合观测、奖励和结束条件接入经验池；目前尚未实现。
5. 右臂验证通过后再迁移左臂，重新核对接收端配置与方向。

操作命令、参数和接口细节见[手柄控制教程](../../../../tutorials/gamepad_control.md)。

## 后续：SDK 输出坐标与旋转格式适配

用户观察右摇杆左推导致上下移动，检查所提供 SDK_PYTHON.zip 后确认：
`solve_tcp_delta_ik` 区分 BASE/TCP，且后三维要求 ABC degree，而策略内部为旋转向量。
实际接收程序的 frame/UserFrame 尚未取得，不能认定现象的唯一原因。

新增 `real/sdk_action.py`，两种发布入口共用输出 wrapper。
可显式选择 `--output-convention sdk-x-forward-z-left`，按假设安装方向把平移/旋转向量
从 `(x,y,z)` 换为 `(x,-z,y)`，旋转再转换为 SDK `Rz(C)Ry(B)Rx(A)` ABC 角。
默认 legacy 保持原输出；sdk-base-aligned 仅适配旋转格式。
63项相关测试通过，尚未实机验证；接收端须使用 FRAME_BASE 并核对 UserFrame。
具体启动命令见[教程](../../../../tutorials/gamepad_control.md#sdk-单臂安装坐标转换-wrapper)。

## 继续现场试运行前的记录

用户要求记录后继续使用原程序验证。入口仍为 `scripts/gamepad_test.py`，无需换程序；
必须退出旧进程并带新参数重新启动，运行中的旧进程不会自动更新代码。

```bash
cd /home/zhoutong/omi_folder/omi_proj
source scripts/env_ros.sh
export ROS_DOMAIN_ID=13
python scripts/gamepad_test.py --execute --scale 0.5 \
  --output-convention sdk-x-forward-z-left
```

按回车开始发送，RB 按住运动、松开零增量；默认10Hz，合速度上限5mm/s、5degree/s。
纯单轴满输入应输出：向前 `[0.5,0,0,0,0,0]`，向左 `[0,0,0.5,0,0,0]`，
向上 `[0,-0.5,0,0,0,0]`，均为最终 SDK 消息（mm/degree）。
先核对接收端 FRAME_BASE=0 和 UserFrame，再逐轴短时确认实际方向；
实际接收程序尚未取得，安装矩阵仍为假设，不把预期输出当作真机验证结果。
截至本条记录，换轴后的真机试运行结果待用户反馈，助手未启动真机发布进程。


## 输出可观测性与教程整理

按用户要求，两个手柄入口现显示同一次采样的原始动作、转换是否启用/模式、换轴与 ABC 转换标记，以及最终输出。
原始值是经过死区/scale/符号和 RB 判断后的策略系动作，以 mm/旋转向量degree展示；
SDK 模式的最终值为 mm/ABC degree。零动作也显示实际配置的转换开关，不按数值是否变化推断。
区分“仅预览”和“已发布”，后者不代表设备执行成功。日志补充原始显示值与转换开关。
直接脚本打印频率仍为约2Hz，动作默认10Hz，不为打印额外读取一次手柄。

最新相关测试67项通过。已重整手柄教程：两种入口、跨机环境、默认legacy、不带参数不换轴、
scale与坐标转换的区别、最终SDK协议、操作映射、日志字段和未验证边界均明确记录。
助手未启动真机动作发布；换轴后的现场验收尚待用户反馈。
