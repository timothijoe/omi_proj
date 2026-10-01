# 模型与 A 臂到达任务

`TianjiAReachEnv` 继承通用七维关节增量环境，显式接受 `scene` 路径；若未给路径，可用 `OMI_TIANJI_SCENE`。外部 MJCF 必须包含 `left_joint1..7`、`act_left_joint1..7`、`left_palm_tcp_site`。代码不会下载模型，也不会修复缺失的 mesh；场景编译失败会在初始化时报错。`sim.preflight --scene` 返回映射、关节范围、初始/目标 TCP、控制周期与阈值。

动作空间为每轴 `[-1,1]`，单步最多 `0.04 rad`，控制周期 `0.1 s`。目标 TCP 来自预设目标关节构型的正运动学；成功阈值 `0.035 m`，最大 80 步。`reset_noise_rad=0.03` 用于训练和评估，手动键盘默认零扰动。观测为 14 维关节位置/速度、TCP 位置及目标 TCP 位置。训练可用 progress 奖励；评估由 TCP 误差判定。真人键盘命令 `1+..7-` 只在 MuJoCo 中执行，`r` 复位、`q` 退出。

`sim.interactive_rollout` 加载训练快照，每步先计算策略建议；空回车执行策略，`1+..7-` 或 `h` 使用人工关节增量或保持覆盖，经同一环境入口执行并记录来源。这是等待终端输入的逐步式仿真接管，未验证实时连续操控。

自包含 `tianji_7dof_surrogate.xml` 是零重力接口夹具；默认 `TianjiSurrogateEnv` 保留旧的关节目标任务。它的几何、限位和动力学不能迁移到真机。外部场景也尚未校准到现场设备，掌心 TCP 可能不是现场工具 TCP。可视化代码用 EGL 离屏渲染，不等同于 GUI 验收。[2026-10-01 编年记录](../chronicles/2026-10-01-a-arm-reach.md)保存首期实验结果。
