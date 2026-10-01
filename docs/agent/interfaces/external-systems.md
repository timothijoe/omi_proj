# 外部系统与参考边界

**MuJoCo/Gymnasium：**当前实际仿真运行栈。外部 MJCF 来自 `cooking_proj` 的本地非跟踪资源；不能凭模型文件名推断现场动力学已校准。

**Tianji SDK：**`TJ_FX_ROBOT_CONTRL_SDK/SDK_PYTHON` 提供控制类和原生动态库。OMI 的 `TianjiSdkArm` 用依赖注入完成假 SDK 测试，实际 SDK 加载、控制器兼容性及任何设备连接未验收。A/B 映射在现有 `cooking_proj` 实验中为左/右；现场仍需核对。

**参考 HIL-SERL：**原版项目用于算法和干预流程对照，LeRobot 版是计划复用的 actor/learner 基础。当前 OMI 的训练实现是 SB3 单进程仿真，不应称作 LeRobot 分布式系统。[早期调查](../../tianji_hil_rl.md)保存适配分析。[当前训练事实](../training/evolution/hil-training.md)为准。
