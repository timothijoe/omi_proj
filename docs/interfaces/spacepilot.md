# SpacePilot 输入与位姿导出契约

采集/在线RL新增[HIL输入profile](../modules/teleoperation.md)：`omi-spacepilot-hil-input-v1`、固定axis_frame、`buttons`为逻辑码字符串→libspnav实体ID，默认保存在local/spacepilot/hil_buttons.json。它独立于本页位姿快照。配置及使用见[HIL教程](../../tutorials/spacepilot_hil.md)。

另有独立的[末端增量发送入口](../../tutorials/spacepilot_control.md)：使用同一设备映射，按速度生成增量并经 SDK 转换发送；不读取本页 JSON 位姿。其连接、动作与验证边界见[控制纪传体](../modules/teleoperation.md)。下文仅描述原位姿演示。

范围：本地物体位姿演示。当前能力见[纪传体](../modules/teleoperation.md)，操作者看[教程](../../tutorials/spacepilot_pose.md)。

## 入口与依赖

公开启动入口为 `bash scripts/spacepilot_pose.sh [--probe SECONDS] [--output-dir PATH]`。
开发模块入口为 `PYTHONPATH=src /usr/bin/python3 -m omi_hil_rl.hardware.spacepilot_pose`，从仓库根执行。
脚本自动切到仓库根；相对输出路径相对于仓库根。直接模块调用相对于调用者当前目录。
`OMI_SPACEPILOT_PYTHON` 可指定具备 Tk 的其他 Python 解释器。

需要 Linux、Python 3.12（本机验证版本）、Tk、libspnav、运行中的 spacenavd；GUI 还需桌面 DISPLAY。probe 无需显示服务器，但当前模块仍导入 tkinter，需安装 python3-tk。安装的 Python CLI entry point 不存在，不要使用 `omi-spacepilot` 等未定义命令。

GUI 内部由 `SpaceNav.poll` 非阻塞轮询 ctypes 事件；设备名称同步查询每秒一次。模块中的 `map_motion`、`select_axes`、`integrate` 和 `Viewer` 为内部实现，不承诺跨版本 API。驱动按键 ID 使用零起算值，GUI 历史映射为实体 1/2/3 对应 12/13/14。后续用户在机器人控制入口报告实体3上报 ID19，该入口默认启用键已改为19；不能将旧 GUI 映射视为所有当前设备配置的固定关系。

## 坐标与单位

场景采用右手坐标：前 +X、左 +Y、上 +Z。输入映射及手感修正以[纪传体](../modules/teleoperation.md)为准。
位置为米，内部角速度为 rad/s，UI 旋转速度为 °/s；导出的 RPY 为度。
四元数为 `(w,x,y,z)`，表达物体坐标到世界坐标的旋转。
`R = Rz(yaw) Ry(pitch) Rx(roll)`。世界模式左乘姿态增量，局部模式右乘；导出始终是世界位姿。

## JSON 快照

点击「导出位姿 JSON」保存当前一个位姿，没有轨迹或设备原始流；默认目录 `local/spacepilot/`。

```json
{
  "frame": "right-handed X-forward Y-left Z-up world",
  "position_m": [0.0, 0.0, 0.0],
  "position_order": ["x", "y", "z"],
  "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
  "rpy_degrees": [0.0, 0.0, 0.0],
  "rpy_convention": "R = Rz(yaw) Ry(pitch) Rx(roll)"
}
```

这是演示场景的独立快照，无机器人名称、时间戳、TCP 校准或协议版本。不能直接作为机器人动作、训练 transition 或 ROS 消息。

## 副作用与退出

导入和 help 无设备连接；GUI/probe 连接本机驱动、接收输入，不改变系统驱动配置。仅用户执行导出时创建目标目录/文件；脚本本身不自动记录日志。关闭窗口释放 libspnav 连接，驱动作为系统服务继续运行。设备丢帧保护和重连行为不是机器人急停接口。
