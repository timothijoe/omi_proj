# 2026-10-07：按回合交替 RL 最小闭环

用户希望当天跑通流程，本次实施，不自动启动真实机器人。

入口 `scripts/run_alternating_rl.sh` / `hil/alternating.py`：
离线准备 v2 → 等人工开始 → 执行/采集 → 异步落盘完成 → 独立进程有限次 SAC 更新
→ 检查精确目标版本并重载/试推理 → 等下一次人工开始。
默认人工动作；`--enable-policy` 才允许 ACTIVE 回合内模型均值动作。RB 优先。

复用 `_collect` 并增加动作/边界/阶段回调，人工采集原入口保持默认行为。
RosTransport 子类区分 receiver manual route 与 policy route，command audit 从实际发布 trace 取 topic。
主线程处理 ROS/手柄，writer 写盘线程，独立 learner 进程；加载/预热在线程中，期间主线程继续 idle_tick。
训练任务只在 ready 回合产生后启动；checkpoint 更新号精确匹配 base+N 才允许下一回合。
learner 对已有交替调度目录拒绝无当前 episode 授权的普通启动。

手柄修复：LinuxGamepad 保留单次 poll 内按钮事件序列，ButtonEvents 处理短按再释放；
初始化按下不触发，手动停止与成功同时出现时停止优先；auto review 模式忽略 keep/discard。

持久化 `alternating_state.json` 和 `tasks/<episode>.json`；异常任务不自动重放，进入 PAUSED。
支持正常边界续跑；异常/断电后的训练任务恢复仍需人工检查。不是完整持久任务队列。
模型版本按回合记录。退出保留完整回合，部分回合审计排除。原始采集文件不修改。

局限：未真机联调，未验收物理坐标；新策略效果未知，初始头非 BC 热启动；
有限 replay 可能淘汰演示数据；保留 100 ms 新鲜度门槛；未移植314自动回位；
初始化沿用历史数据 episode duration 和完整契约，不能随意更改时长混用。

详细命令和边界：[教程](../../../../tutorials/alternating_rl.md)。
测试见 `tests/test_alternating_rl.py`：短按、子进程响应、版本/阶段顺序、失败不重启、
未确认任务拒绝恢复，以及实际 CPU SAC 子进程两回合训练/重载/入池闭环（合成观测）。

验证结果：10组相关测试共98 passed、1 skipped（沙箱CUDA不可见）。
沙箱外GPU准备成功：`local/rl_training/alternating_20261007_01/`，capacity2000，
训练8回合929条、留出2回合222条，batch2实际更新2次，actor重载最大误差0，冻结权重不变。
创建机器人发布者0。report.json保留证据。留出MSE从0.62479到0.68766，更新后222条dx均负；
只证明训练/保存/重载流程，不证明策略可部署，明确建议先默认人工模式跑现场回合。
