# 2026-10-01：A 臂末端到达仿真闭环

**当时目标：**按用户选择使用 SDK A 臂，找到 `cooking_proj/docs` 指向的天机 MJCF，选定首任务与遥操作方式，建立可视验证。

**实际实现：**在另一份本地 `cooking_proj` 检出找到完整 `right_chopping_scene.xml` 及 mesh；当前工作区不包含这些非跟踪资源。加载场景后确认 `left_joint1..7`、`act_left_joint1..7` 和 `left_palm_tcp_site`，建立固定 TCP 目标到达任务。提供预检、键盘逐关节点动、SAC 训练、独立评估、JSONL 校验与 EGL 离屏 PNG/GIF。示范文件可导入训练经验池。

**当时证据：**外部场景 headless 加载成功；脚本示范 7 步到达；1500 训练步含 709 个脚本接管步，1500 条 transition 校验通过；独立 30 回合评估为 30/30，平均 8.27 步；策略可视化回合误差 0.319 m → 0.011 m；自动测试运行结果为 23 passed。[实验报告](../../../a_arm_reach.md)与 [PNG](../../../evidence/a_reach_policy.png)、[GIF](../../../evidence/a_reach_policy.gif) 保存细节。

**当时限制：**模型资产不在本仓库；没有人工 GUI/Viewer 观察、设备只读连接或真机运动。固定目标与小幅初始扰动使任务简单，结果不能外推到实机。

**后续影响：**建立了训练和硬件适配共用的动作来源契约，下一步需要现场模型与设备验收。
