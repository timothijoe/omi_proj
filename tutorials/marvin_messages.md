# 项目本地 marvin_msgs 消息包

`/tj/info/joint_feedback` 使用自定义类型 `marvin_msgs/msg/Jointfeedback`。
ROS能发现话题名，但本机没有加载类型时，`ros2 topic echo`会报message type invalid。

2026-10-04已把现用消息源码复制到项目local，并在干净的Jazzy环境重新编译。
不是复制旧build/install；原Downloads副本保留，不影响已有终端或历史路径。

## 当前路径

```
local/ros2/marvin_msgs_ws/
  src/marvin_msgs/          # 源码：Jointfeedback、JointcmdArm
  source_provenance.json   # 原始来源、逐文件SHA256
  build/                   # 本机Jazzy构建产物
  install/                 # 本机Jazzy/Python3.12消息类型
  log/                     # colcon构建日志
```

`local/`不进入Git。该包是早期录包工具从MCAP schema恢复的两个消息定义，
不是完整厂商接口仓库，也不包含控制器或设备连接程序。定义与迁移前完全一致；
现场不同消息结构需使用匹配接口，不能因包名相同就认定兼容。
项目`ros2/live_feedback_interfaces/`的现场接口另有用途，此次不替换它。

## 每个新终端使用

```bash
cd /home/zhoutong/omi_folder/omi_proj
source scripts/env_marvin.sh
export ROS_DOMAIN_ID=13
ros2 topic echo /tj/info/joint_feedback
```

`env_marvin.sh`只加载系统ROS与消息overlay，不激活训练venv、不修改domain或网络发现配置。
保留机器人连接时的网络设置；本机有类型不等于已验证远端消息格式和通信。
`OMI_MARVIN_MSGS_SETUP`若已显式设置，优先沿用；想切回默认local包可先
`unset OMI_MARVIN_MSGS_SETUP`，再source。无需修改全局.bashrc。

现有`env_ros.sh`在本地包存在时自动加载它，保留原venv行为；
机器人回放入口的默认路径和本机`local/robot_state/viewer.env`也已更新。

检查：

```bash
ros2 pkg prefix marvin_msgs
ros2 interface show marvin_msgs/msg/Jointfeedback
```

prefix应指向当前项目`local/ros2/marvin_msgs_ws/install/marvin_msgs`。
本机已验证两个消息Python导入及Jointfeedback的CDR序列化/反序列化。

## 换机器或重建

拷贝整个`src/`和`source_provenance.json`。在目标机器匹配的ROS发行版/Python下重新构建，
不要跨ROS发行版复制build/install。以下为本机Jazzy命令，使用未激活conda/训练venv的干净终端：

```bash
source /opt/ros/jazzy/setup.bash
cd /path/to/omi_proj/local/ros2/marvin_msgs_ws
colcon build --packages-select marvin_msgs --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
```

本机install是Jazzy/Python3.12，不能直接加载到Humble/Python3.10。
若在另一工作区或发行版构建，显式设置OMI_MARVIN_MSGS_SETUP指向匹配overlay，
并让OMI_ROS_DISTRO与目标ROS保持一致。缺依赖时需要目标ROS的colcon和rosidl构建工具。
