# 2026-10-07：共享编码器、HIL-SERL 对齐与中断恢复

## 结论与范围

用户要求：暂时共用编码器，网络架构和参数尽量对齐 HIL-SERL，保留当前输入，
并避免采集/训练必须一直运行、程序中断后无法继续的问题。

已实现新 RL 版本 `omi-hil-sac-shared-serl-v2`，以及断点续采、多目录离线训练和训练安全退出。
本阶段只做软件与离线验证，没有启动机器人运动，也没有完成 v2 正式训练或真机成功率验收。
这些改动不能作为此前后退问题已解决的证据。

操作入口：[采集/续采/续训教程](../../../../tutorials/rl_episode_collection.md)、
[网络与参数说明](../../../../tutorials/hil_actor_learner.md)。

## 网络和参数

- Actor 和双 Q 共享同一个 Encoder 对象；目标 Q 的编码器是独立副本。
- Critic 优化器独占共享融合编码器；RL Actor 对融合特征停止梯度，只更新策略头，避免重复优化共享参数。
- 保留双相机、触觉网格、EEF、十帧历史与掩码；离线入口仍关闭六维力/力矩输入。
- Actor 头为 128→256→256→12，输出六维均值和六维 log_std；双 Q 头各为 134→256→256→1。
- 按官方 MLP 的 activate_final=False，仅第一层后使用 LayerNorm(eps=1e-6) 和 tanh；网络头使用 Xavier 初始化、零 bias。
- tanh Gaussian 标准差限制为 [1e-5,5]；温度使用 softplus，初值 .01，目标熵 -3。
- lr=3e-4、gamma=.98、tau=.005、Critic/Actor 更新比 2:1；目标使用最小 Q、不加熵，Actor 使用平均 Q。
- 训练新增 padding=4 随机裁剪；每个样本/相机独立，窗口内十帧使用同一偏移，观测和下一观测独立增强。
- RL 默认 batch256；可以显式32降低显存需求，但这不等于梯度累积或官方batch256。

仍然是 PyTorch 适配实现，不是官方 JAX 数值等价复现。保留的输入融合适配器输出128维，
官方独立 proprio 投影的梯度路径未原样复现；保留梯度范数5限幅、人工奖励与 timeout bootstrap、
当前动作坐标和幅度。没有新增夹爪，也没有承诺对齐架构即可保证学习成功。

## 版本兼容

v1 Learner/优化器不能直接恢复为 v2，必须新建训练目录；原始采集文件可继续使用。
旧 BC 入口显式使用 LegacyActor，避免 RL 架构改动影响已有 BC；v1 actor 仍按旧结构加载推理。
未覆盖、删除或转换原始采集数据和旧 checkpoint。

2026-10-06 的 `local/rl_training/offline_20261006_v1/` 是旧版102次更新的流程验证，
不是新架构训练结果，也不是已经可部署的策略。

## 中断与数据恢复

| 场景 | 当前行为与边界 |
|---|---|
| 采集正常 Ctrl+C | 先停止，排空后台写盘；完整回合保留，未结束回合仅审计 |
| 采集加 --resume | 校验原契约，读取已有回合清单，追加新回合；等315重新开始，不续发旧动作 |
| 崩溃留下 staging | 没有 ready 的回合标记 discarded，不猜测成功或奖励 |
| 多次采集 | --source 接受多个目录，契约须一致，拒绝重复目录/episode ID；全局按回合划分训练和留出 |
| 训练 Ctrl+C/SIGTERM | 转成停止请求，当前完整更新结束后保存退出，不在半次优化器更新时保存 |
| 训练 --resume | 恢复模型、目标 Q、优化器、温度、随机状态与原 replay；updates 是追加次数 |
| 更新内部异常 | 保留上次完整 checkpoint，不发布可能半更新的参数 |
| 强杀/断电 | 不能保证零损失；未写盘队列可能丢失，训练回退到上次完整 checkpoint |
| dirty replay | 仍拒绝加载，需要依靠完整原始回合重建；未实现自动修复，不可手工伪造 clean |

离线 --resume 固定使用原 dataset 快照，不自动吸收之后新增的回合。
新增数据可新建训练目录合并来源；在线持续导入仍需接通并验证对应 Learner 交接流程。
恢复进程不代表恢复机器人位置，物理复位仍由人工完成。

## 代码定位

- `src/omi_hil_rl/hil/networks.py`：共享编码器、网络头、SAC、增强、版本兼容。
- `src/omi_hil_rl/training/demo_bc.py`：显式保留旧 BC Actor。
- `src/omi_hil_rl/hil/collect_episodes.py`：采集续写与孤立回合隔离。
- `src/omi_hil_rl/hil/offline_train.py`：多来源划分、离线训练和续训。
- `src/omi_hil_rl/hil/shutdown.py`：延迟处理 SIGINT/SIGTERM。
- `src/omi_hil_rl/hil/learner.py`：完整更新边界退出，异常时保留旧 checkpoint。
- `src/omi_hil_rl/hil/exchange.py`：原子文件发布后的目录 fsync。

## 验证与待办

上一实现阶段相关测试结果：72 passed、2 skipped（CUDA不可用）。
覆盖共享参数唯一优化器归属、目标编码器独立、分布边界、增强时间一致性、
真实已采观测CPU更新/重载/一致续训、更新中SIGINT保存恢复且不重复导入、
采集续写/孤立回合排除、多来源划分和BC/Replay回归。
本次整理文档没有重新运行训练或硬件测试。

尚未验证或完成：v2 GPU batch256显存占用、正式学习效果、真机在线闭环成功率、dirty replay自动恢复。
此前307/308短按漏检与标签核实问题不在本次修复范围；用户暂按既有标签有效进行流程验证，
不能由此推断现场标注准确性已得到确认。

下一阶段应先做新架构独立训练/评估，再验证策略执行、RB接管、数据入池与权重更新的在线闭环。
不要把旧版诊断结果或本次通过的单元测试当作新策略上线许可。
