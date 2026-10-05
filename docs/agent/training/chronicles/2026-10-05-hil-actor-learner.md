# 2026-10-05：六维真机 HIL、双 Critic 与 Actor/Learner

用户要求先实现真机环境、无夹爪但带 Critic 的策略网络、Actor/Learner。
回合采用人工开始、人工成功、开始后 15 秒超时，以及整段人工保留/丢弃。

新增 `src/omi_hil_rl/hil/`，包括配置、Gym 生命周期、ROS/合成 transport、
当前帧/历史视觉触觉 EEF Encoder、Gaussian Actor、双 Critic/target/温度、
磁盘 episode spool、唯一 learner 写入、权重发布、干净检查点恢复与 CLI。
真实编码结构使用已有 no-joint current9stack，冻结官方视觉骨干，控制头与 Critic 从头初始化。
BC checkpoint 仅用于观测统计和契约；不导入未来状态代理标签作为执行动作。

默认配置沿用安全预览方向：合成入口明确标记 fake，ROS 默认无动作 publisher。
新增接收端 tagged receipt，并适配工作区同期的“逐控制周期 IK”实现，保存已有人工路由/保护修改。
回执报告采用、SDK 子指令发送/结束取消及故障，绝不声称实际位移完成。
SAC 动作分量默认 1mm/√3、1°/√3，范数不超过既有默认单步上限；不对 Gaussian 动作事后径向投影。
HIL RB 动作遵守接收端保护，不走另一人工保护旁路。

整段先落压缩磁盘文件，结束后审核，再逐 transition 导入已有 memmap replay。
失败/超时的有效段允许保留；异常段丢弃。在线 human 进两流、在线 policy 进 RL、
成功离线全人工示范只进 Demo。超时 bootstrap 保留，成功禁止 bootstrap。
Learner 可以连续抽 transition batch 更新，而不是每 episode 只更新一次。
本机文件交接不是跨机器 gRPC；单环会覆盖老 Demo，图像历史暂未去重。

验证：42 项软件测试通过，包含按钮/计时/审核、timeout target mask、分流、
导入预检查和 journal、SAC 参数更新/骨干冻结、checkpoint 重载、独立进程 Actor/Learner。
真实多模态网络用本地官方 backbone 完成 CPU/CUDA 梯度更新和恢复一致性验证；没有启动真机。
CUDA 专项 3 项通过；真实 encoder 使用合成输入以默认 batch32 完成2次更新，
RTX5060Laptop峰值已分配显存约813MiB，约0.93秒；仅为软件 smoke，非训练收敛结果。
接收端与保护回归 48 项通过、1 项 schema 测试排除。
42 项软件通过，CPU 解释器中的 CUDA case 跳过；CUDA case 已在独立 GPU 环境验证。
接收端使用断开连接的 ROS 节点和假 IK/SDK 验证回执；涉及当前 schema 的既有
`test_default_does_not_load_sdk_or_connect` 与安装的 Jointfeedback 字段不一致，单独记录环境问题，
未更改该既有测试或消息包。

操作和精确验证边界见 [教程](../../../../tutorials/hil_actor_learner.md)。

## 进展讨论归档

用户询问当前进展后，明确将当前阶段记录为“三项软件实现完成，真机联调前”。
随后按用户要求补充 docs 当前专题和 tutorials 下一阶段操作顺序，并更新入口索引。
本次只整理文档，测试数字沿用上面的实现阶段证据，没有重跑测试、启动机械臂或真机训练。

当前事实见 [专题](../evolution/hil-actor-learner.md)，操作见 [教程](../../../../tutorials/hil_actor_learner.md)。
