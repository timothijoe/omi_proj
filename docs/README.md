# OMI 文档总目录

本项目目前是天机 Marvin **A 臂（左臂）**的 MuJoCo HIL RL 原型。当前状态以 [能力总表](capabilities.md) 和各领域 `current.md` 为准；历史实验数字保存在编年记录中。

## 选择入口

| 读者 | 从这里开始 |
| --- | --- |
| 第一次运行 | [环境准备](../tutorials/environment_setup.md) → [最短仿真案例](../tutorials/quickstart.md) |
| 操作键盘示范或回放 | [键盘示范](../tutorials/keyboard_demonstration.md) → [录制与训练](../tutorials/recording_and_replay.md) |
| 核查 HIL RL 四项复现 | [训练、干预、buffer、policy improvement 审计](hil_rl_reproduction.md) |
| 开发与维护 | [Agent 知识库](agent/README.md) → [接口索引](agent/interfaces/README.md) |
| 理解边界 | [安全与副作用](safety.md) → [跨领域设计](design/hil-architecture.md) |

现有 [A 臂实验报告](a_arm_reach.md) 保存可复现实验与证据；[早期技术调查](tianji_hil_rl.md) 保留当时的 SDK 和参考项目分析。功能的**当前事实**由 `agent/*/evolution/` 维护，避免把早期计划误认为现状。
