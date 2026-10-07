# USB 插入触觉保护

## 行为和边界

`arm_delta_cmd` 接收端保护默认关闭，显式 `tactile_guard_enabled:=true` 开启后检查两根手指的
`/omi/tactile_grid24x16/{a,b}/wrench`，**只约束模型动作**。
模型通道为 `/omi/action/decision` (`delta_topic`)，手动通道为
`/omi/action/manual_decision` (`manual_delta_topic`)；两者必须不同。
手柄普通控制、RB 接管和手动通道的回位动作均不受触觉保护影响；推理入口默认单按314回位，直接手柄入口默认使用RB+回位键。
但仍受原有 IK、工作空间和关节步长等限制。手动通道是可信操作员入口，
不是认证/鉴权边界；其他程序不得把模型动作发到手动通道绕过保护。
这是实验性位置指令保护，不是硬件急停或经认证的安全功能。
本次只完成离线验证，没有连接、切模式或驱动真机。

保护采用固定夹持基线：`ΔF = F - Fbaseline`、`ΔT = T - Tbaseline`。
任意一根手指的三维力变化模长达到 `tactile_force_limit`，或力矩变化模长达到
`tactile_torque_limit`，单帧即触发并锁定。不要求两个手指同时超限，不混加力和力矩。

| 状态 | 接收端行为 |
| --- | --- |
| 尚未显式采集基线 | 所有模型动作禁止，包括模型撤退 |
| 两侧健康且未触发 | 原有动作和限幅逻辑保持不变 |
| 已触发，且两侧数据健康 | 只接受 `dx < 0`；其余五个分量归零，限制撤退步长和速度 |
| 一侧缺失、无效或超过超时未收到消息 | 所有模型动作禁止，包括模型撤退；恢复数据也不会自动解锁 |
| 模型反馈保持指令尚未成功 | 所有新模型动作禁止，继续尝试保持；手动接管可覆盖待保持状态 |
| 手柄手动控制 | 不读取触觉保护条件，断流和超限均不拦截手动控制 |

超限/断流会清空正在执行的模型插补队列，不清空手动队列。下一个控制周期读取关节反馈，发送当前反馈位置作为
新的 SDK 位置参考，并把 IK 起点重新锚定在反馈上，避免旧目标继续拉向接口。
模型保持失败时不放行新的模型动作，手动接管不受该等待状态限制。
保持位置不等于卸载接触力；硬件/SDK 故障仍需物理急停处理。

当前契约严格采用 **SDK Base 坐标的负 X 作为撤退方向**。
现有左臂策略映射保留 X 的符号，但这不是实测插入轴标定。实机开启前必须确认
负 X 确实离开接口；换姿态、换安装方向后不可盲用。
开启保护时拒绝 `delta_frame=tcp` 配置。受保护的模型撤退使用 Base 增量话题。
`dx < 0` 与侧移/旋转组合时只保留撤退，不放行整个组合动作。

## 默认参数

| ROS 参数 / launch 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `tactile_guard_enabled` | `false` | 显式启用模型保护 |
| `tactile_force_limit` | `2.0` | 相对基线的三维力变化模长阈值 |
| `tactile_torque_limit` | `0.5` | 相对基线的三维力矩变化模长阈值 |
| `tactile_timeout` | `0.2` | 任意一侧主机接收超时，秒 |
| `tactile_retreat_step_mm` | `0.2` | 每条被允许的撤退动作最大位移，毫米 |
| `tactile_retreat_speed_mm_s` | `2.0` | 撤退插补的名义最大速度，毫米/秒 |

力/力矩数值仍是 **未标定 SDK 单位，不是已经验证的 N 或 N·m**。
`2.0 / 0.5` 来自 2026-10-05 截图对应记录中的平稳段与大峰分离情况，
只是初始实验候选，尚未确认正常插入误报率、卡住前提前量和接口损伤上限。
启用保护不意味着这些数值已经安全认证。先在无接口接触、低速和可物理急停的
条件下验证方向和触发逻辑，再用标注过的正常/异常插入数据选择阈值。

消息使用主机单调时钟计算接收年龄，不依赖 ROS 时钟跳变；但 SDK 没有可靠设备采样
时间/序号，所以无法识别“不断发布同一个旧 SDK 结果”。该机制不能替代设备端
新鲜度证明。执行器响应、ROS 调度和 SDK 调用也存在延迟，不保证立即物理停止。
速度上限通过控制周期的插补步长实现，是目标参考的名义上限，不是测量到的 TCP 速度。

## 使用步骤

先重新构建接收端，并在新终端加载更新后的 overlay：

```bash
bash scripts/robot_controller.sh build
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export ROS_DOMAIN_ID=13
```

现有现场接收端需要重启后才能使用新保护；仅重启模型没有作用。
本教程不自动连接机械臂或启动真实动作。接收端仍需原有的连接和运动授权参数。
在原现场 launch 命令上添加：

```text
tactile_guard_enabled:=true tactile_force_limit:=2.0 tactile_torque_limit:=0.5
```

关闭使用 `tactile_guard_enabled:=false`，此时不要求基线，也不订阅触觉或发布保护状态。
参数只在启动时读取，修改开关或阈值需要重启接收端，当前不支持动态 `ros2 param set` 生效。
手柄直接入口默认发送 `/omi/action/manual_decision`；策略仲裁器把 `human/human_home`
发到手动通道，把 `policy/paused_*` 发到模型通道，切换时向旧通道发零取消残留动作。
接收端和发送端都必须升级。手柄日志新增 `command_topic`；录制动作时需包含两个话题。

1. 暂停模型/手柄动作；夹住 USB，确保尚未接触接口，保持稳定。
2. 确认两侧触觉流正常；需要各 20 帧最近的稳定样本，窗口不超过 1 秒。
3. 显式采集基线（这一步会解除“未采集基线”的启动阻塞）：

```bash
ros2 service call /delta_ctrl_node/capture_tactile_baseline std_srvs/srv/Trigger '{}'
```

基线不能在插补进行中或反馈保持待完成时采集。
同一进程内只允许采集一次，避免把过载重新归零。每轮需要新基线时暂停控制并重启
接收端，重新确认夹持和方向；普通复位始终保留原基线。

4. 查看状态，再进行受控测试：

```bash
ros2 topic echo /omi/safety/tactile_guard
```

状态 JSON 包含 `state`、`reason`、`latched`、两侧 `metrics`、固定 `baseline`、
阈值和 `pending_feedback_hold`。`clear` 才表示普通动作可以通过。

5. 触发后，双侧数据有效且持续收到时，模型可给出负 X 动作撤退，即使受力仍然很大。
   触觉数据真正断流/无效时模型无法撤退，但操作员仍可以用手柄自由控制；不会自动撤退或松夹爪。
6. 暂停撤退。两侧数据恢复健康，且力/力矩变化都低于各自触发阈值的一半后，显式复位：

```bash
ros2 service call /delta_ctrl_node/reset_tactile_guard std_srvs/srv/Trigger '{}'
```

复位后上游新动作可立即通过，因此复位前应暂停策略输出；不要按着运动键复位。
外部直连 SDK 的其他程序、夹爪驱动和绕开本接收端的控制路径不在此保护范围内。
默认关闭是用户要求；USB 插入策略实验应显式开启并检查状态。

## 与 / 或关系

```text
触发过载 = A力变化≥力阈值 或 A力矩变化≥力矩阈值
        或 B力变化≥力阈值 或 B力矩变化≥力矩阈值

数据健康 = A消息持续收到 且 A六分量有限有效
        且 B消息持续收到 且 B六分量有限有效

锁定后的模型撤退 = 基线存在 且 数据健康 且 dx<0 且 无待完成的模型反馈保持

允许复位 = 数据健康 且 基线存在 且 A力变化<半力阈值 且 B力变化<半力阈值
        且 A力矩变化<半力矩阈值 且 B力矩变化<半力矩阈值
        且 插补已停止 且 无待完成保持 且 人工请求复位

手动动作 = 不参与上述触觉判断，只走原有控制限制
```

“数据健康”不要求力小，不要求低于触发阈值。力很大且数值有效是过载，不是传感器失效。
复位才要求回落到半阈值以下；撤退本来就是为了让力降低，不会要求先卸载才准模型撤退。

## 离线验证

```bash
source /opt/ros/jazzy/setup.bash
source local/ros2/robot_controller_ws/install/local_setup.bash
export ROS_DOMAIN_ID=114 ROS_LOCALHOST_ONLY=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q \
  tests/test_tactile_guard.py tests/test_robot_controller_migration.py
```

测试包含两侧六分量正负超限、预载基线、峰后锁定、低阈值复位、断流/NaN、
撤退投影、取消模型队列、反馈保持/失败阻塞、单拆分配置下撤退限速，以及默认关闭、
手动控制不受影响和双通道来源路由检查。
所有执行器测试使用 fake SDK/IK，不连接真实机器人。
