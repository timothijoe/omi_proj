# Tianji SDK 适配器

`hardware.tianji_sdk` 提供 `TianjiConfig`、`TianjiArmState` 和 `TianjiSdkArm`。SDK Python 类和 `DCSS` 可注入，用于假设备测试；实际加载时需指定 `sdk_root`。SDK 中 A/B 对应 `outputs/states` 的索引 0/1，SDK 关节角为**度**，OMI 状态为**弧度**。`connect()` 连接并读取，不切换控制模式；`read_state()` 检查七关节、帧号递增时效与错误码。

`arm_position_mode()` 要求 `motion_authorized=True`、反馈已递增及 SDK 模式切换确认。`send_joint_target_rad()` 检查状态、现场配置的关节限位和最大单步差，再转换为度送 SDK。`stop()`、`close()` 处理软停止、下使能和释放。当前 `executed_action` 训练契约尚未绑定真实反馈，适配器不构成可运行的真机 HIL 环境。

配置参数目前没有现场值，也没有实机 CLI。假 SDK 和 MuJoCo 替身验证只能算自动测试；设备只读、位置模式、物理急停与真实运动尚未验收。[编年记录](../chronicles/2026-10-01-sdk-boundary.md)保存阶段证据。
