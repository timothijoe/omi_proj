# Simulation 当前摘要

`TianjiAReachEnv` 在外部双臂场景中控制左 A 臂七个关节，任务为掌心 TCP 到固定目标；同时保留自包含零重力代理模型。预检、脚本示范、键盘点动、策略运行中的逐步键盘接管和离屏 GIF/PNG 已有入口。外部 MJCF 在本机完成 headless 加载与运行，自动测试覆盖 A 臂映射、到达和接管动作；没有 GUI/Viewer 人工验收，也没有真机模型一致性验收。

最新结构、参数与限制见 [模型与任务](evolution/model-and-task.md)；形成记录见 [2026-10-01 阶段](chronicles/2026-10-01-a-arm-reach.md)。近期方向是现场核对关节顺序、TCP 与模型资产恢复流程。
