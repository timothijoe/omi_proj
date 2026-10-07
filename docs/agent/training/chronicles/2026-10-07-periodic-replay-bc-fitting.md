# 2026-10-07：周期控制、成功动作回放与 BC 拟合诊断

## 当前结论与交接入口

本次完成：BC周期发送模式、成功回合动作label回放、单回合过拟合诊断及独立评估导出、
全8回合两阶段BC训练。**不是完成了BC初始化的在线RL训练，也没有真机成功率结论。**

- 现场运行先看[BC模型与label回放测试](../../../../tutorials/bc_replay_testing.md)。
- 训练复现与完整数值见[异步RL/BC教程](../../../../tutorials/async_rl.md)。
- 最新评估目录：`local/bc_episodes/all8_coarse_fine_eval_01`，模型version11795。
- 旧多回合BC version295、单回合模型version3295以及原始数据均保留。
- 用户反馈单回合模型的运动“和之前比有区别”；没有给出重复试验成功率或确认插入成功。
  用户曾提供周期模式运行日志，证明现场进入ACTIVE、切换human、结束并写审计；
  不能将“助手未驱动机器人”写成“用户从未试运行”。

## 1. 为什么拆开控制和回执配对

此前 `RosTransport.interact()` 把发送动作、完成回执、因果下一观测和下一候选交接串在一起。
其中任一环节在等待窗口内未满足，就报 `missing command receipt or causal next observation`，
BC回合无效并PAUSED。该日志本身不能断定是RGB或接收端哪一个慢。

HIL-SERL的官方Franka普通step是提交目标、补足周期时间、读取实际状态；服务端发布目标后
返回，并不等待机械臂到达。它仍有HTTP和取图等开销，不能保证硬实时10Hz；
异步Actor/Learner也不等同于动作发送完全无阻塞。
参考[环境step](https://github.com/rail-berkeley/hil-serl/blob/main/serl_robot_infra/franka_env/envs/franka_env.py)
与[服务端pose/move](https://github.com/rail-berkeley/hil-serl/blob/main/serl_robot_infra/robot_servers/franka_server.py)。

新增 `hil/periodic_control.py`，接入 `run_bc_episodes.sh --control-mode periodic`（BC默认值）：

- 目标每100ms发送，不逐条等待完成回执或完整transition；调度落后跳过时槽，不突发追赶。
- 推理仍为后台线程；只执行与对应观测匹配、未使用、年龄小于100ms的候选，缺失则零动作。
- RB优先、连接检查保留。human/policy分别通过零动作回执验证Arm A/base/10Hz velocity_hold。
- 持续1秒无已知命令回执、明确接收端拒绝、手柄断连或写盘异常仍停止；不是关闭全部安全检查。
- 有界队列及独立写盘线程保存到 `periodic_episodes/<id>/`；Ctrl+C先停止输出，再排空记录。
- `audit.json`、`pairing.json`、逐周期NPZ与`receipts.jsonl`用于审计；`training_ready=false`，
  不生成旧式`ready.json`，不自动导入RL buffer。最后一个无可重建后继快照的点不伪造有效transition。
- `--control-mode receipt`保留旧同步配对。**run_async_rl.sh尚未迁移到这个周期模式。**

接收端是velocity_hold：新命令替换旧保持值，`velocity_window_sent`不证明实测到达。
不能把queue_replaced/接收确认当成物理执行完成。

## 2. Label replay 与网络推理必须区分

`run_bc_episodes.sh`始终是实时BC推理，不因为加periodic就变成数据回放。
新入口 `scripts/replay_success_episode.sh` / `hil/replay_actions.py` 才播放历史动作。

验证回合：`local/rl_episodes/test_20261007_161750/episodes/71960bbce1d24bd9ad9060cb95d0663f`。
ready标记成功，171条全为人工来源，发送时间跨度约17.5秒；dx有68条正、103条零、无负数。
该回合在原version295的**训练集**中，BC监督目标直接取`executed_action`，不是EEF位移差。

| 项目 | Label replay | 实时BC |
|---|---|---|
| 六维归一化动作来源 | 保存的executed_action | 网络根据观测预测 |
| 物理量换算 | config.physical_action | 同一函数 |
| 换轴/单位/发布 | policy路由，复用_publish | 同一policy路由 |
| 调度 | 原记录发送间隔，开环 | 实时观测/候选门控 |

回放前检查成功/保留标记、契约、顺序、有限值、原动作/回执/重建SDK指令一致。
默认只检查和打印，无ROS发布者；显式`--execute --output <新目录>`才连接控制端。
315开始，先零动作验证policy接收端；末端反馈新鲜且起点偏差不大于10mm/5度才允许播放。
原始间隔非正或超过250ms拒绝；运行落后超过50ms停止，不补发突发动作；末动作只保持一个名义周期。
RB取消本次序列并允许人工控制，松开不恢复旧序列；307/308停止，Ctrl+C退出。
程序不自动移动到起点，也不能验证物体位置与夹持状态一致。记录在`commands.jsonl`，不是BC新示范或RL buffer。
label的`normalized`与最终`wire`不能混用；回放来源是人工记录，但本次发送标记policy。

## 3. 单回合容量诊断

`hil/overfit_episode.py`从原BC version295继续训练上述171条；输入、归一化、结构不变，
视觉预训练骨干冻结。训练和评价是同一回合，不代表泛化。

| 实验 | 归一化MSE |
|---|---:|
| 原BC在此回合 | 0.03472836 |
| 冻结编码器、只训输出头3000步中的最佳 | 0.01654205 |
| 原有可训练编码器+输出头1000步，lr=1e-4 | 0.00168793 |
| 从上一结果再细调2000步，lr=1e-5 | 0.00009889 |

未发现完全相同输入对应冲突标签；这不排除相近观测的动作歧义。
当前架构能拟合这条示范，不能直接归因于容量不够；仍不能证明学到了跨回合可泛化表征。
两种模式预算不同，冻结特征实验不能作为严格容量上限证明。

诊断目录为`local/diagnostics/overfit_71960_20261007_01`及`overfit_71960_20261007_refine_01`。
原始诊断权重故意不是部署格式；用户要求加载后，使用`hil/prepare_overfit_eval.py`显式导出，
得到`local/bc_episodes/overfit_71960_eval_01`，version3295。
GPU重载171条预测最大差0；CPU最大差约0.00555、MSE约0.0001001。没有把数值差异隐瞒为完全一致。

## 4. 全8回合两阶段拟合

用户要求使用全部8个有效回合。源索引仍为原BC数据集，1296条：6成功、2超时，均为人工动作。
原6训练/2验证全部纳入拟合，导出的索引保存`original_split`并将`split`设为training。
**现在没有独立验证集；“best”是训练集MSE最好，不是任务成功率最好。**

入口`hil/fit_all_bc.py`，从原version295开始而非单回合模型：

- Adam，batch16、seed7、归一化统计沿用原模型；骨干冻结，其余原可训练编码器和输出头更新。
- 第一阶段4000步lr=1e-4；第二阶段从第一阶段最佳3750步权重开始，重建Adam，8000步lr=1e-5。
- 执行12000次更新，全量MSE最低在累计11500步，导出version11795；计数不等于单一路径连续Adam状态。
- 没有Critic训练、在线RL更新或探索方差标定；不能直接用作SAC learner恢复点。

整体MSE `0.0462581 → 0.00088644`，下降约98.1%；明确dx动作方向准确率95.81%→100%。
433条全零标签上，每样本最大绝对预测分量的均值0.31522→0.04361；残余动作未彻底消除。
单轴平移MAE约0.01070/0.01260/0.01352mm，旋转约0.00869/0.01075/0.00843度。
最大单分量预测误差仍约0.629，不能由平均误差推断每步可靠；上述不是机械臂定位误差。

产物：`local/rl_training/bc_all8_coarse_fine_20261007_01`（actor、report、history、前后预测、带原划分索引）。
独立评估快照：`local/bc_episodes/all8_coarse_fine_eval_01`，version11795；GPU重载全部预测最大差0。
原模型哈希未变，快照哈希校验通过。运行时会打印OVERFIT_EVAL，明确泛化未验证。

## 5. 代码与验证

- 控制/回放：`src/omi_hil_rl/hil/{periodic_control,replay_actions,bc_rollout,ros_transport}.py`。
- 训练/导出：`src/omi_hil_rl/hil/{overfit_episode,prepare_overfit_eval,fit_all_bc}.py`。
- 测试：`tests/test_periodic_control.py`、`test_replay_actions.py`、`test_bc_rollout.py`、
  `test_hil_behavior_cloning.py`、`test_fit_all_bc.py`。
- 最后全8回合相关子集13项通过；回放/周期控制早先子集16项通过，测试集合有重叠，不能相加。
- 真实记录离线检查、CUDA训练及模型重载已完成；助手未发布真机运动指令。

`local/`下的数据和权重是本机产物，不应假定仅克隆Git即可获取；跨机需按路径另行拷贝并校验。

## 6. 后续工作

后续状态更新：下面第3、4项已在同日继续开发，代码、验证及剩余限制见
[BC保护式RL与编码器说明](2026-10-07-bc-protected-rl-and-encoder.md)。以下列表保留本阶段原始待办。

1. 用新采集的独立回合评价8回合模型，记录成功率、停止动作偏差和离开示范状态后的行为。
2. 针对同一观测做在线/离线路径一致性审计，再判断真机偏移来自输入、学习还是控制。
3. 若要把periodic审计数据用于RL，先定义速度保持/替换下的transition及缺失数据处理，再实现导入，不能直接冒充旧ready。
4. 在线RL的BC初始化、Critic预训练及BC约束更新仍须另行实现；本次没有接通。
