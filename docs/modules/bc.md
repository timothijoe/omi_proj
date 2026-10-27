# 示范采集与 BC

职责：保留可审计的人工动作，构造与输入契约匹配的数据，拟合初始Actor并为在线RL提供权重。主要实现位于 [hil](../../src/omi_hil_rl/hil)，采集入口 `collect_rl_episodes.sh`，周期数据准备 `prepare_periodic_bc.py`，训练 `behavior_cloning.py` 与 `fit_all_bc.py`。

## 数据与标签

当前主链使用控制端已接受的命令增量作标签；它不等于测得的EEF位移。早期bag实验的未来EEF变化代理标签、未确认关节目标标签是不同契约，不能直接混入当前数据。

SpacePilot采集松开Menu后输出人工零动作；在线RL松开则归还策略。正常超时或普通结束可作为BC数据，成功与否和标签可用性分别审核。断连等异常回合排除。快速启停的指令仍保留审计，训练片段需满足实际连续性与间隔约束。见 [采集教程](../../tutorials/rl_episode_collection.md) 和 [人工输入](teleoperation.md)。

按原始回合划分训练和验证，不能将同一回合不同片段分到两边；归一化只统计训练数据。读取时核验manifest与样本哈希。十帧历史、mask与动作范围必须与checkpoint匹配，详见 [数据接口](../interfaces/data-formats.md)。

## 选定BC来源

10月17日SpacePilot源为 `local/rl_episodes/spacepilot_response_20261017_213359`。10个原始回合中9个正常、1个断连排除；正常回合导出41个连续片段、1499样本。先用7个回合1174样本训练、2回合325样本留出选择初始版本148。

全量拟合从148开始：2000步lr1e-4，再从粗训最佳权重重建Adam并微调4000步lr1e-5，得到BC6148。最终1499样本训练MSE约0.00223588。全部正常数据均用于最终拟合，没有独立最终测试集；命令误差不是机器人定位精度，也不证明闭环成功。

模型路径：`local/rl_training/spacepilot_bc_20261017_213359_2000_4000/actor.pt`。这些local产物不随Git交付。当前在线初始化只继承权重与归一化，不自动导入这1499条数据，见 [在线RL](online-rl.md)。

## 固定模型与辅助工具

固定BC评估 `run_bc_episodes.sh` 只推理和录制，不启动Learner；它的 `--resume` 与在线RL自动续跑不同。录制完成不等于已进入RL池，需要显式来源配置及导入校验。

独立rosbag采集/审阅仍由 [demo_bag_dataset](../../tutorials/demo_bag_dataset.md) 支持；旧影子BC工具见 [bag_bc_shadow](../../tutorials/bag_bc_shadow.md)。这些辅助入口沿用各自数据契约，不自动替代主链。

尚需独立评估：不同初始姿态泛化、自主成功率、零标签残余动作与触觉贡献。历史拟合改善不能单独说明真机策略改善。

开发历史（按需）：[BC阶段与实验归档](../archive/bc/README.md)；BC6148完整阶段记录也在 [在线RL归档](../archive/online-rl/README.md)。
