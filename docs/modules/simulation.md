# 仿真模型与任务

职责：验证动作、仲裁、奖励、回放和策略评估，不提供未经现场确认的动力学或安全参数。入口 [TianjiAReachEnv](../../src/omi_hil_rl/sim/tianji_a_reach.py) 使用外部双臂MJCF，仅控制A左臂七关节；自包含Surrogate只是接口夹具。

## 模型与任务契约

显式scene或OMI_TIANJI_SCENE定位本地资产，模型须包含left_joint1..7、act_left_joint1..7和left_palm_tcp_site。缺mesh或编译失败会报错，不自动下载修复。`sim.preflight`核对映射、范围、TCP和控制周期。

动作每轴[-1,1]，最大0.04rad/步，周期0.1s；目标来自固定关节构型FK，TCP误差小于0.035m成功，最多80步。观测包含七关节角/速度、TCP和目标TCP。训练progress奖励与评估sparse奖励分开，不能拿不同奖励口径直接比较。

`sim_train`使用SB3 SAC，可选示范BC和双流回放，记录仲裁/限位后最终命令。脚本教师与真人终端接管都标记human，单看来源标签不能证明真人参与。

## 操作和证据

[最短案例](../../tutorials/quickstart.md)、[模型准备](../../tutorials/a_arm_simulation.md)、[键盘示范](../../tutorials/keyboard_demonstration.md)、[录制与回放](../../tutorials/recording_and_replay.md)。逐步终端接管等待输入，未验收连续低延迟遥操作。

历史1500步低熵SAC在固定简单目标下独立30回合30/30成功，EGL离屏图像和GIF已保存；默认熵纯SAC曾失败。该结果不代表跨目标泛化、真机效果或MuJoCo GUI人工验收。场景安装、关节限位、工具/TCP和真实设备一致性尚未全面验收。

动作单位与真机六维末端策略不同；不复用仿真关节限位作为真实控制安全边界。资源不随Git完整交付，见 [资源接口](../interfaces/local-resources.md)。

开发历史（按需）：[仿真归档](../archive/simulation/README.md)。
