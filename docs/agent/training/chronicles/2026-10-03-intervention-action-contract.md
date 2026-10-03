# 2026-10-03：HIL-SERL 人工接管与 ROS 动作接口讨论

## 目标与结论

用户询问干预和不干预是否共用 topic，并要求核查原版 HIL-SERL 的实现；认可解释后，
要求保存 Markdown。采用更新既有参考纪传体和影子推理设计、另增本篇编年的组织方式，
不新建重复的独立方案或操作教程。

原版在 Python 环境包装器中整步选择策略或人工动作，统一调用环境执行；接管时通过
`info["intervene_action"]` 返回人工动作，覆盖训练循环中原候选后写经验。
所有在线经验进在线池，干预经验另外进示范池；Learner 两池各采半个 batch。
选定动作不等于底层限幅后的目标或实测反馈。原版输入回零恢复策略，不代表完整安全机制。

对 OMI 认可的方向：策略/人工候选分来源入口，统一选择并保留动作来源；共同决策出口
可覆盖干预和自主两种情况，策略推理输出仍只表示模型建议。拟采用类型化消息，不让两个
发布者争抢控制指令。具体字段、恢复自主条件及安全修改后的训练语义仍待实现/确认。

## 证据与边界

- 静态复核同级 `hil_serl_projects/hil-serl`，HEAD 为
  `c32939bccb65f3b8c43a9f9add3d322d4ab0264a`，工作树无修改。
- 已阅读 `SpacemouseIntervention`、`train_rlpd.py`、`RelativeFrame` 和 Franka `step`。
- 核对 OMI `src/omi_hil_rl/training/bc_shadow.py`，预测仍通过 String JSON 发布；
  类型化动作消息和该 ROS 链路的接管选择模块尚未实现。
- 仅修改文档及术语；未运行原版训练、未连接设备、未改控制代码，未执行 commit/push。
- 原有未提交代码和文档保留；此记录不表示它们已提交或重新验收。

## 长期入口

- [HIL-SERL 参考纪传体](../evolution/hil-serl-reference.md#人工接管动作记录与训练采样)
- [ROS 影子推理设计与待实现接口](../../../design/bag-bc-shadow-policy.md#人工接管与类型化动作接口待实现)
- [统一术语](../../../../CONTEXT.md)
