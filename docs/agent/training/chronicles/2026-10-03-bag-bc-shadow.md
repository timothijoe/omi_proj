# 2026-10-03：真实录包BC训练与ROS影子推理第一版

用户要求先将目标写入md，再实现真实训练与录包模拟在线推理。
先写[目标](../../../design/bag-bc-shadow-policy.md)，再新增三个training模块、bag_bc.sh、测试和教程。
保留已有未提交可视化工作，未调用设备、发布控制命令或自动commit/push。

## 数据和实际训练

读取oct2/record001.zip，SHA256
`708fbd8aab565b28ce34c796d8b6d652129ccb6022872bd08ae85bed57e82f7f`。
数据位于 `local/bc/record001_dataset/`，manifest记录契约、指纹、计数和丢弃原因。

- 136个10Hz参考；缺RGB6点、缺a_deformation15点、触觉过旧6点；109个有效观测。
- 末尾1个缺未来标签，最终108个训练样本，NPZ约4.7MiB；另存只含观测的MCAP。
- 目标最大绝对值1.51919 rad，与反馈最大差约0.04 rad；不证明单位或动作语义。
- 500步、seed7、CPU PyTorch2.14.1+cpu，实际反向与Adam更新，约2.77秒。
- 同段目标RMSE：未训练0.00752417 → 训练后0.00178072 rad；保持关节基线0.00804263，
  固定平均目标基线0.04561033 rad。
- 输出 `local/bc/policy_record001_smoke/{policy.pt,report.json,train_predictions.npz}`。
- 明确标记overfit_smoke_not_generalization，validation=null，不报告伪造任务成功率。

## ROS真实消息回放推理验收

两独立进程，localhost domain99，每轮第6秒故意暂停1秒；通过ROS传感器订阅构建输入，
而非直接读NPZ冒充在线接收。共享预处理，逐样本输入SHA256核对。

首次报告 `local/bc/shadow_record001_smoke/report.json`：
218预测、每轮109；输入全匹配；两次重置/暂停检测，无控制topic、错误或超时。
模型耗时p50/p95/max约0.815/0.979/25.050ms，参考后等待6.609/26.675/26.911ms。

增加严格的每轮预测数量验收后，复验报告 `local/bc/shadow_record001_verified/report.json`：
仍为218次、每轮109；无错误、超时或控制topic，正常完成两轮。
模型耗时p50/p95/max约0.796/1.005/45.377ms，参考后等待14.204/16.975/18.570ms。
有标签预测RMSE 0.00178072 rad，与离线一致。每轮多于108训练样本的一次，是末尾
观测有效但无未来动作标签的帧。等待/推理时间不等于真实曝光到控制执行延迟。

## 边界与后续

自动测试最终128 passed、5 skipped，新增7项覆盖分块均值/符号、因果取样、过旧/缺失、
循环重置、有界历史、真实梯度训练与权重重载、重复episode拒绝、训练统计不泄漏验证集、
动作假设门禁和影子域隔离。Shell语法、三个子命令help、diff空白检查通过。
大资源Git忽略确认通过，ROS实跑后无相关子进程残留。未执行GUI或设备验收。

左臂7轴绝对弧度目标只是显式实验假设；消息定义没有证明控制器实际执行。
单包缺独立成功示教，不能证明泛化或插孔；未来需真实episode边界、成功标记、时间和动作语义确认。
腕部缺失、TCP映射及触觉幅值问题没有被本轮修复。影子预测不改变录包后续数据，不是闭环。
真实设备采样调度、Humble/GPU、长期吞吐、现场安全控制及预训练/时序模型留待后续。
现状见[纪传体](../evolution/bag-bc-shadow.md)，操作见[教程](../../../../tutorials/bag_bc_shadow.md)。
