# 外部系统与参考边界

**Daimon SDK：**重建/真实触觉采集的外部运行依赖，已本地归档于 `local/vendor/daimon_tactile`，
不进Git。Python/架构/固件匹配及依赖安装必须另验；新数值场看板仅订阅消息，不依赖SDK。

**ROS/RealSense：**独立OMI采集包随源码交付；系统ROS、官方驱动、存储插件和RViz在目标机安装。
自定义marvin_msgs另取匹配源码构建，只服务旧关节反馈/完整observation路径。
参考工程不是整体运行依赖。具体资源、源位置和恢复方法见[转移清单](../../../tutorials/machine_transfer_checklist.md)。

**MuJoCo/Gymnasium：**当前实际仿真运行栈。外部 MJCF 来自 `cooking_proj` 的本地非跟踪资源；不能凭模型文件名推断现场动力学已校准。

**Tianji SDK：**`TJ_FX_ROBOT_CONTRL_SDK/SDK_PYTHON` 提供控制类和原生动态库。OMI 的 `TianjiSdkArm` 用依赖注入完成假 SDK 测试，实际 SDK 加载、控制器兼容性及任何设备连接未验收。A/B 映射在现有 `cooking_proj` 实验中为左/右；现场仍需核对。

**参考 HIL-SERL：**原版项目用于算法和干预流程对照，LeRobot 版是计划复用的 actor/learner 基础。当前 OMI 的训练实现是 SB3 单进程仿真，不应称作 LeRobot 分布式系统。[早期调查](../../tianji_hil_rl.md)保存适配分析。[当前训练事实](../training/evolution/hil-training.md)为准。
