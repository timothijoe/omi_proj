# Training 当前摘要

目前使用 Stable-Baselines3 SAC 加可选示范行为克隆更新、`HILReplayBuffer` 双流混合采样、JSONL 逐步录制和可选示范预填。训练时由脚本教师按概率接管；策略运行中可用键盘逐步覆盖，真人长回合可用性尚未验收。固定种子评估和策略快照能追踪 policy improvement：默认熵 SAC+BC 与低熵纯 SAC 都在 1500 步从 0/10 到 10/10；默认熵纯 SAC 在 1500 和 5000 步均失败。低熵纯 SAC 另取 30 回合为 30/30。LeRobot HIL-SERL 的分布式 actor/learner 尚未接入。

最新机制与限制见 [HIL 训练数据链](evolution/hil-training.md)；形成过程见 [首期编年](chronicles/2026-10-01-hil-sim-training.md)、[双流审计](chronicles/2026-10-01-policy-improvement-audit.md)及[低熵纯 SAC 实验](chronicles/2026-10-01-low-entropy-sac.md)。
