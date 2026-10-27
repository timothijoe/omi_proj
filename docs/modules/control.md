# 机器人控制

职责：接收选定动作，进行单位/坐标转换后的增量执行、IK、SDK提交及反馈。真实接收端维护于 [ros2/arm_delta_cmd](../../ros2/arm_delta_cmd)，与早期七关节 `TianjiSdkArm` 是两条不同路径。

## 执行链与契约

Actor → 策略/人工ROS通道 → `delta_ctrl_node` → IK与SDK → 关节/EEF反馈。默认策略topic为 `/omi/action/decision`，手动为 `/omi/action/manual_decision`；专用测试入口可以配置其他topic，不应混用。

网络内部动作是基座系六维米/弧度旋转向量；SDK出口转换 `(x,y,z)→(x,-z,y)` 并将旋转向量转ABC，只转换一次。接收端wire为六维mm/ABC度，ABC组合 `Rz(C) Ry(B) Rx(A)`，不是三个旋转向量分量。

接收端把名义10 Hz增量乘以输入频率得到速度，在默认200 Hz控制周期做小增量IK并下发。`manual_command_rate`、`policy_command_rate`必须匹配输入；`delta_splits`仅兼容保留。运行中IK以最近命令目标为锚点，不是每步都从当前反馈起算；调度延迟不补发积压大步。

代码入口：[delta_ctrl_node.py](../../ros2/arm_delta_cmd/arm_delta_cmd/delta_ctrl_node.py)。默认start_mode=3，手动/策略断流阈值均0.25秒，每周期关节限幅2°，连接时TCP球形包络默认100mm。这些是软件参数，不是现场安全验收值。

默认断开，连接需显式motion_authorized。工具参数在切模式前经clear/set/send设置，启动失败即退出。反馈约50 Hz；关节度转弧度，EEF由反馈FK并左乘安装矩阵。A臂固定安装为平移(0,0.0260,1.121)m与Rx(-90°)，不是自动读取外部TF的标定结果。

## 停止和回执的实际含义

普通零动作只清速度和have_goal、停止新增目标，不用反馈替换最后SDK目标；实际机械臂仍可能追踪最后目标。断流和软件停止不等于物理急停。

无ID零停止仅取消自身通道，避免跨topic迟到停止覆盖另一来源；带HIL ID的零动作可以正式接管。`velocity_window_sent`表示观察周期结束，`velocity_hold_continues`表示仍保持速度，`execution_confirmed=false`明确不证明物理到达。

触觉保护默认关闭；开启后只约束策略通道。锁定时仅双侧数据健康才允许受限Base -X撤退，手动通道不受该触觉拦截。健康只表示接收数值有效，不代表力低或单位已标定。详见 [保护教程](../../tutorials/tactile_guard.md)。

## 已知缺口与证据

10月17日200 Hz/模式3的四段记录，全零后约0.22–0.30秒近停，X拖尾约0.44–0.92mm；阈值、平滑窗口及原始条件见 [控制响应证据](../evidence/control_response_20261017/README.md)。这不是一般停止距离保证。

旧500 Hz日志的clear_set=0对应SDK本地发送状态忙，不能简单解释成控制器拒绝。当前点位提交仍有clear_set失败后继续设置目标、send_cmd返回值未检查便推进本地目标的缺口；工具初始化的返回值检查不能替代该运行路径检查。

需要同一时钟记录命令回调、SDK耗时/返回值、目标和反馈才能继续定位迟滞。未实施新的反馈保持策略、统一平移旋转缩放或独立加速度平滑。缺反馈、目标锚点、ABC重复组合、安装/TCP一致性仍需现场验证。

操作见 [构建与运行](../../tutorials/robot_controller.md)、[人工输入](teleoperation.md)。开发历史（按需）：[控制模块归档](../archive/control/README.md)。
