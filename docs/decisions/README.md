# 长期原则与决定

这里保留仍有效的设计约束，具体后端和当前运行行为见[模块导航](../README.md)。

- [最终接受动作入池](training-001-executed-action-replay.md)
- [在线与示范分流](training-002-dual-stream-replay.md)
- [默认只读与显式运动门](hardware-001-readonly-motion-gate.md)
- [外部场景资源](simulation-001-external-scene.md)
- [训练原则](training-principles.md)、[硬件原则](hardware-principles.md)、[仿真原则](simulation-principles.md)

早期决定中的ring-buffer等实现范围须按当前cached／旧memmap／仿真后端区分，不能据一份历史决定推断所有后端相同。
