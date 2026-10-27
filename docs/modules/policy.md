# 策略模型与动作

职责：将多模态十帧观测编码为特征，输出六维机械臂命令。真机编码器见 [networks.py](../../src/omi_hil_rl/hil/networks.py) 与 [eef_bc_stack.py](../../src/omi_hil_rl/training/eef_bc_stack.py)，精确shape见 [数据接口](../interfaces/data-formats.md)。

## 当前真机结构

current9stack对每路相机分别编码当前RGB三通道和过去九帧拼接的27通道；当前帧不混入历史分支。两视角共享ResNet-10骨干，四个视觉投影分别保留当前/历史、外部/腕部特征。没有GRU或attention。

双指触觉数值场逐时刻经共享小CNN，再按十个时刻展开。状态容器仍为14维，但当前真机无关节模型忽略前7维，使用EEF xyz/xyzw及mask。缺失图像、触觉和状态槽依照mask置零，不能把缺失当成有效黑图。

真机SAC复用编码器的128维融合特征，Actor为六维tanh高斯，Critic接特征与动作。视觉归一化、触觉/状态训练统计和base_contract随checkpoint保存。可选wrench_history有独立分支与契约，不能因看板有wrench就宣称所有模型都使用它。

当前主配置从BC6148热启动：视觉（含历史首层及投影）和融合层冻结；1000次Critic预热后触觉CNN训练。Actor和Critic共享编码器，可训练触觉参数归Critic优化器，Actor更新不重复拥有该参数。目标网络和固定BC参考不直接做梯度更新。

## 动作契约

[HILConfig](../../src/omi_hil_rl/hil/config.py)定义六维归一化分量[-1,1]，乘会话保存的action_scale得到米/弧度旋转向量。SpacePilot新采集范围与旧手柄不同，不能按默认值重新解释旧数据。夹爪不属于策略动作。

标签是仲裁后已接受的命令；噪声审计保存均值、噪声和实际增量。SDK出口再做换轴与ABC转换，见 [控制模块](control.md)。当前位姿、命令锚点、旋转向量与ABC不能混称；历史policy_scale与分别范数限幅工具属于独立推理入口，不应代替HIL动作契约。

## 辅助模型和验证范围

CNN/GRU、ResNet/GRU、无关节对照、旧关节BC和EEF代理标签模型保留实现与复现资料，不作为当前真机默认。六关键点预标注/人工审核是独立工具，未接入当前策略损失，见 [标注教程](../../tutorials/six_keypoint_review.md)。

已有离线拟合、CPU/CUDA一致性和选择性训练探针；不据此推断触觉解冻提升了自主成功率，也不把单次GPU推理时延当端到端闭环时延。

使用见 [BC模块](bc.md)、[在线RL](online-rl.md)。开发历史（按需）：[模型与消融归档](../archive/policy/README.md)。
