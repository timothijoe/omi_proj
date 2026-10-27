# 策略模型历史

保留旧关节／EEF代理模型、ResNet历史、无关节和current9stack对照。当前真机是六维accepted-command与选择性触觉训练，不能把旧实验动作范围、wrench分支或训练结果直接套到新任务。

这里只保存原过程、旧方案与证据，原文的“当前”有时间范围。日常阅读见[当前说明](../../modules/policy.md)。

## 阶段记录

- [2026-10-03：bag_004末端动作空间第一版](records/training/chronicles/2026-10-03-eef-action-space.md)
- [2026-10-03：1秒历史GRU训练与单帧对照](records/training/chronicles/2026-10-03-history-gru-training.md)
- [2026-10-04：独立 CUDA 环境与策略推理时延对照](records/training/chronicles/2026-10-04-cuda-policy-latency.md)
- [2026-10-04：当前帧独立与过去9帧拼接对照](records/training/chronicles/2026-10-04-current-stack-history.md)
- [2026-10-04：在线历史推理与 wrench 有效性标签](records/training/chronicles/2026-10-04-history-online-wrench.md)
- [2026-10-04：禁用关节反馈的GPU训练](records/training/chronicles/2026-10-04-nojoint-gpu-training.md)
- [2026-10-04：下载预训练ResNet-10并重训历史policy](records/training/chronicles/2026-10-04-resnet10-history.md)
- [2026-10-04：无关节模型实时影子推理入口与现场阻塞](records/training/chronicles/2026-10-04-stack-live-shadow.md)

## 原机制与领域摘要

- [当前帧独立与历史通道拼接](records/training/evolution/current-stack-history.md)
- [左臂末端增量动作与录包代理标签](records/training/evolution/eef-action-space.md)
- [在线历史 policy 与可选 wrench](records/training/evolution/history-online-policy.md)
- [禁用关节输入的历史拼接模型](records/training/evolution/nojoint-stack.md)
- [冻结 ResNet-10 与历史 GRU](records/training/evolution/resnet10-history.md)

## 旧教程与导航快照

- [当前帧独立＋过去9帧通道拼接](tutorials/current_stack_history.md)
- [末端动作 rosbag 与模拟控制端联调](tutorials/eef_action_bag.md)
- [不使用关节反馈的历史拼接策略：GPU训练](tutorials/nojoint_stack_training.md)
- [冻结ResNet-10历史策略实验](tutorials/resnet10_history.md)
