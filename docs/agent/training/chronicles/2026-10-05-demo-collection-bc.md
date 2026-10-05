# 2026-10-05：独立示范采集与命令监督 BC

本篇记录早期集成collector及软件验证阶段。随后用户改用独立gamepad纯录包，并完成四个真实包采集、检查和逐帧查看；当前状态见[后续四包编年](2026-10-05-passive-demo-audit.md)。下文“未运行真机采集”及“bag含精确快照”仅指当时集成模式阶段。

需求：不依赖已有模型先采集人工示范，保留观测以后计算 reward，并把手柄实际发送 topic 作为动作标签。
完成独立 collector、ROS raw bag/命令 trace/回执配对、纯人工回合审核、按 episode 划分、磁盘流式 BC、版本化 reward 后标注及确定性 Actor 读取。
操作见[教程](../../../../tutorials/demo_collection_bc.md)，契约见[专题](../evolution/demo-collection-bc.md)。

验证结果：

- Demo pipeline + HIL runtime：24 passed、2 skipped（CPU 环境跳过 CUDA）。
- 独立 CUDA 真实多模态 BC 梯度专项：1 passed，确认冻结骨干和可训练层更新。
- 指令 trace / 实际 rosbag / 接收端回执：6 passed；录包测试使用隔离 ROS_DOMAIN_ID=231 和测试 topic，无真机命令。
- CLI 流程产物：`local/demo-workflow-review/`。6 段合成示范，每段 8 条，共 48 条；4 段训练、2 段验证，100 次更新。
- 验证集归一化 MSE 从 0.0309899 降至 0.00000971485；零动作基线 0.0314245，训练均值基线 0.0000760727；最佳权重重载及独立 evaluate 一致。

合成动作是可预测脚本，仅证明流程可学习、可保存和复现，不是人工采集结果。
真实多模态梯度测试也不代表真实示范上的 BC 效果。本次没有启动机器人运动或测量插入成功率。

## 后续：三个独立脚本与逐帧可视化

新增[录制、转换、查看教程](../../../../tutorials/demo_bag_dataset.md)与默认双相机必需的 ROS 配置。
新 bag 内记录精确样本快照，可仅从 bag 恢复 NPZ，不按不同接收时钟重新近邻匹配。
新增 HTTP 查看器：双 RGB、双指 deformation/shear/depth、历史槽、动作条形图、EEF、时间/回执，支持PNG导出。
综合回归38 passed、2 skipped（CPU环境的CUDA项）；覆盖隔离DDS大图像消息实际录包、bag独立读取、逐数组一致、坏哈希/缺样本/非法路径拒绝、HTTP和图像通道顺序。
脚本CLI串联产物 `local/demo-bag-tools-review/`，1段2样本的合成测试bag和转换后数据集；图像含随机测试字节，不是真实示范。
页面脚本语法检查、Shell语法检查和PNG人工查看通过。未运行真机采集，未测量新增快照通信在现场的持续吞吐。
