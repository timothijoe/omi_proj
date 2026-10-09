# 2026-10-09：Start 保留 SAC 十帧输入历史

## 问题与目标

用户反馈：手柄按住 Start 开始 SAC 回合时，已经积累的十帧输入被丢弃，
仍需等待约 1 秒才能使用网络。希望保留开始前的最近十帧。

代码检查确认，`RosTransport.wait_start()` 在等待按键时持续调用 `_pump()`，
已经按 100 ms 周期建立滚动观测；但 `RealHILEnv.reset()` 和 `run_periodic()`
在收到 Start 后调用 `reset_history()`，清空传感器缓冲、历史窗口及时间基准，
使每个新回合重新积累十帧。Start 本身按按下边沿触发，长按不会反复开始回合。

## 完成修改

- 新增 `RosTransport.start_episode()`：新回合只使旧策略动作候选失效，
  保留传感器缓冲、最近十帧和原有 100 ms 时间基准；后续 pump 用保留的有效观测重新推理。
- `RealHILEnv.reset()` 与周期控制 `run_periodic()` 改用 `start_episode()`；
  同步回合、异步 RL 周期回合、BC 周期评估和人工周期采集共用此行为。
- `reset_history()` 仍提供显式清空历史的能力，预览入口继续使用；
  `FakeTransport.start_episode()` 保留合成测试所需的回合状态重置。
- 新增 `tests/test_start_history.py`，并调整周期控制测试替身的生命周期接口。

历史缓存足够且新鲜时，Start 不再强制重新积累约 1 秒的输入。缓存继续滚动，
不是冻结 Start 前的十帧，也不是复制同一帧补齐窗口。保留的是观测上下文，
回合外人工复位动作不会因此转换为训练 transition。

## 保留的门控与计时

首次启动尚未积累十帧、传感器缺流或观测过期时，仍需等待完整有效输入。
同步入口会等待观测；周期策略入口缺少新鲜候选时仍发送零动作，接收端握手也仍保留。
因此，本修改消除了清空缓存造成的额外预热，不保证按 Start 后立刻发送非零策略动作。

回合仍从 Start 开始计时，必要的观测准备包含在原时长内。按键边沿、RB 接管、
动作有效期、时间因果配对和入池判定沿用原规则。

## 验证与证据

在临时源码副本中使用项目 `.venv` 分组执行以下回归，累计 **107 passed、3 skipped**。
应用后校验文件哈希，源码和测试与已验证副本一致。

```bash
.venv/bin/python -m pytest \
  tests/test_start_history.py tests/test_periodic_control.py \
  tests/test_protected_rl.py tests/test_policy_pipeline.py \
  tests/test_hil_runtime.py tests/test_stack_shadow.py \
  tests/test_demo_pipeline.py tests/test_async_training.py \
  tests/test_rl_episode_collection.py tests/test_bc_rollout.py \
  tests/test_alternating_rl.py -q
```

新增四项测试使用真实 `StackObservations` 与 ROS transport 的 pump/回合逻辑，
传感器和 ROS 时钟由软件替身提供，覆盖：

- 已积累十个不同输入帧时，Start 保留原窗口，模拟启动耗时小于一个 100 ms 周期；
  持续按住 Start 后历史仍滚动，不重复清空。
- 开始回合后旧动作候选失效，后续 pump 可重新提供候选；显式 reset 仍清空历史。
- 只有三帧时仍等待其余真实输入，不补造历史帧。
- 即使曾有完整十帧，传感器停止更新后也不能用过期输入启动同步回合。

跳过项涉及 CUDA 或本地模型产物条件。上述结果是软件回归证据，
没有发布机器人动作或完成实机时延验收。

## 生效与文档入口

已运行的进程不会自动加载新代码。操作者正常结束并等待当前回合保存后，
按原命令重启 Actor／手柄控制程序；不需要为这次缓存修复重新训练或转换模型。
本轮未代替操作者重启真机进程，现场响应时间仍待确认。

当前机制见[真机在线 RL](../evolution/real-online-rl.md#start-与十帧历史)，
操作见[异步 RL 教程](../../../../tutorials/async_rl.md#2026-10-09start-保留十帧输入)
与[人工采集教程](../../../../tutorials/rl_episode_collection.md)。
