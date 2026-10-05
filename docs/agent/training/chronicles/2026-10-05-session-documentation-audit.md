# 2026-10-05：本窗口开发记录覆盖核查

用户要求核查本窗口是否还有开发但未记录的内容。本次对照可见会话、现有源码、文档和本地交接；仅更新文档，没有重新测试硬件、训练或提交代码。其他agent后续工作只链接其记录，不归为本窗口成果。

## 已有记录的开发内容

| 本窗口内容 | 权威记录 |
|---|---|
| 离线成功人工示范进Demo；在线policy进RL、接管进双流；磁盘transition导入 | [双流导入编年](2026-10-05-transition-replay.md)、[磁盘池专题](../evolution/disk-replay.md) |
| 六维无夹爪真机环境、Actor/双Critic、Actor/Learner、开始计时与回合人工审核 | [实现专题](../evolution/hil-actor-learner.md)、[开发验证编年](2026-10-05-hil-actor-learner.md) |
| 先录示范、保留观测与实际发送动作、集成collector和独立手柄两种流程 | [数据契约专题](../evolution/demo-collection-bc.md)、[首版开发编年](2026-10-05-demo-collection-bc.md) |
| 录包topic/位置、all-topics选择、100ms转换、10秒零动作诊断 | [录包转换教程](../../../../tutorials/demo_bag_dataset.md) |
| 六维力补存储、双列布局、四位小数、EEF显示、左右键翻帧、PNG导出 | [四包与查看器编年](2026-10-05-passive-demo-audit.md)、[操作教程](../../../../tutorials/demo_bag_dataset.md) |
| 四包实际审计、消息overlay修正、第三包335条真实指令预览、后继EEF过滤 | [四包编年](2026-10-05-passive-demo-audit.md) |
| 触觉历史为10Hz十槽；显示缩放与原始动作值分开 | [观测/动作专题](../evolution/demo-collection-bc.md) |
| 先备份d317392，再做触觉字段解耦、力独立调度、腕部FIFO与实时/record分流 | [实现纪传体](../../hardware/evolution/sensor-decoupling.md)、[实测编年](../../hardware/chronicles/2026-10-05-sensor-decoupling.md) |
| RGB源header与接收年龄区分、时钟疑点、未实施的接收时间策略 | [时间基准纪传体](../../hardware/evolution/sensor-time-alignment.md)、[排查编年](../../hardware/chronicles/2026-10-05-rgb-clock-and-receive-age.md) |

## 本次补齐与修订

1. 数据契约专题顶部已有后续训练链接，但正文仍写“wrench未进入网络、四包尚未训练”。改为明确阶段事实，并指向其他agent完成的正式passive BC及后续诊断，避免误读当前状态。
2. 补充动作条最右端不是固定0.5或1，而是对应分量的显示尺度；原始动作精度和值不变。
3. 补充后继EEF缺失的时间窗口含义：不能由配对失败直接断定无反馈或低频，第三包167条的统计也不能套用到所有包。
4. 将采集解耦与RGB专题链接补入数据契约页，方便从录包/训练入口找到后续变更。

## 仍未完成的事项不写成成果

- 外部RGB仅按接收时间放行的专用策略仍未实施；源时钟和真实端到端延迟未确认。
- 六维力源采样时间/单位标定、长期无丢帧验收仍无结论。
- 左右键曾做JS语法与HTTP内容检查，未完成自动化浏览器键盘端到端验证。
- 四包成功事件、自动返回段与逐指令执行证据不能从原始bag自动补造；BC训练不等于成功插入或RL闭环验收。
- `/tmp/omi-demo-handoff-20261005.md` 是阶段交接，已有顶部更新但正文保留旧状态；继续工作以仓库最新专题、教程和编年为准，不根据旧PID/服务地址推断进程仍在运行。

本次核查未发现主要开发功能完全没有文档；主要问题是跨阶段表述和查询入口，已按上述范围补齐。测试数字仍引用各实现阶段记录，不作为本次重跑结果。
