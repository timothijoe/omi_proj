# 002：在线与示范双流抽样

**状态：有效。** 在线 transition 进入在线流；发生人工/脚本接管时也进入示范流；导入的离线示范只进入示范流。学习批次按配置从两流抽样，默认各半。单物理ring与成员掩码描述早期仿真实现；当前真机cached使用共享数据条目及两流索引，不能将旧ring覆盖规则套用到所有后端。

原因：原版 HIL-SERL 的在线数据与示范/干预数据分流，离线示范不应被误算进在线半批。影响：buffer 覆盖时必须同步更新掩码，保存/加载时保留掩码，并在训练指标中报告两个流的大小。[当前cached实现](../modules/replay.md)与[原仿真实现记录](../archive/simulation/records/training/evolution/hil-training.md)。
