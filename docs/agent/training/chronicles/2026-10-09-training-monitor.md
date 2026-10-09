# 2026-10-09：Actor / Learner 统一训练监控

## 用户目标与范围

用户讨论 Actor/Learner 异步通信，并希望同一界面观察传感器、仲裁、Learner 与数据链路，
随后授权开发。对照本地原版 HIL-SERL 的 AgentLace 和 LeRobot 的 gRPC 后，
本轮保留已有磁盘交接，先实现可观察性；没有改成网络传输或修改训练预算、动作和换权重节奏。

## 完成内容

- `scripts/view_training_monitor.sh` 与 `hil.training_monitor`：本机只读网页，链路总览、
  Actor/Learner 状态、权重、Replay、排除原因、传感器输入、事件和逐帧回合详情。
- `hil.telemetry`：后台原子快照和独立角色事件日志，区分写者心跳与主循环进度；
  生产循环不等待监控写盘，事件队列有界，监控异常不进入控制判定。
- 异步 Actor、Learner、ROS pump 与周期回合接入遥测。显式显示 SAVING、命令仲裁、
  最新回执、当前进程导入/更新计数和发布确认；保护状态仅订阅，不调用服务。
- 输入预览来自实际模型观测，图像约 1 Hz 重绘、状态快照约 2 Hz 更新；
  触觉箭头隔点显示为 12×8，保持固定尺度，depth 色标固定 0..0.3。
- 原始逐帧审阅复用 `PeriodicReview`，提供回合筛选、周期/历史槽选择、命令 ID、
  配对和导入标记；查看接口没有文件写入或控制 API。
- 扩展回归发现既有缺失后继 EEF 的诊断路径直接访问未初始化 `runtime`；
  改为容错读取计数字典，保留原来拒绝该 transition 的行为。

## 验证与证据等级

使用项目 CPU `.venv`，禁用自动发现的外部 pytest 插件，避免环境中 ROS launch 插件
缺少 PyYAML 影响收集。以下 13 个相关文件共 **126 passed、4 skipped**，耗时 35.07 秒：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  tests/test_training_monitor.py tests/test_async_training.py \
  tests/test_periodic_control.py tests/test_policy_pipeline.py \
  tests/test_protected_rl.py tests/test_dual_replay.py \
  tests/test_hil_runtime.py tests/test_alternating_rl.py \
  tests/test_bc_rollout.py tests/test_command_timing.py \
  tests/test_demo_pipeline.py tests/test_demo_trace_ros.py \
  tests/test_rl_episode_collection.py -q
```

跳过项涉及 CUDA/ROS 运行依赖；没有以 CPU 结果替代这些验证。
新增测试覆盖过期心跳、停滞进度、历史降级、坏 JSON、只读统计、写者 I/O 故障、
生产者不等待写盘、预览缓存/缺输入清除、PNG 数值、HTTP 只读路由及合成 SAC 的
实际导入、更新、发布和退出。已有真实子进程 Actor/Learner 并发回归同时通过。
JavaScript 语法、shell 帮助及源码差异空白检查通过。

真实已有会话只读统计：10 个完整回合加 1 个中断暂存；1959 tick，1059 有效且已导入
transition，0 待导入，1 条成功奖励；旧 Actor 保存版本 650、Learner 更新计数 6502。
旧文件没有发布遥测时页面保留未知，未加载 `.pt` 来猜测发布状态。
本机页面、静态资源和状态 API 的 HTTP 请求通过；测试覆盖图像审阅 API 和非法输入。

真实已录窗口预览短测：预热一次后重复绘制 5 次，平均 17.10 ms、最大 17.75 ms，
8 张预览约 70 KB JSON。该数字只覆盖 CPU 绘图，不是传感器到动作时延或并发最坏上界。

## 尚未验证

Browser 运行时及浏览器发现均未找到可连接的浏览器，未完成实际网页视觉验收。
本轮没有启动设备、发布机器人动作或推进当前真机会话训练；端到端运行开销与
真实长时使用仍待现场验收。自动 UTD 控制、远程通信、策略刷新配置调整和保护开关
不属于本轮实现；原始数据、经验池与模型未被监控开发重写。

操作见[统一监控教程](../../../../tutorials/training_monitor.md)，机制见
[统一监控纪传体](../evolution/training-monitor.md)。
