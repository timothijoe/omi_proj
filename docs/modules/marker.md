# AprilTag标定与跟随

职责：估计末端tag10与目标tag12，保存相对关系并用于复位跟随。**当前选定在线RL配置no_tag_follow=true**，检测/保存/跟随关闭，策略自身的视觉输入仍使用相机。

## 实现与接口

[tag_pose.py](../../ros2/marker_detect/tag_pose.py)估计标签位姿；[tag_handeye_calibration.py](../../ros2/marker_detect/tag_handeye_calibration.py)只读采集多姿态样本求X/Z；[tag_follow_tag_v2.py](../../ros2/marker_detect/tag_follow_tag_v2.py)为独立跟随窗口。共享控制在 [tag_follow.py](../../src/omi_hil_rl/real/tag_follow.py)，训练内会话在 [tag_follow_session.py](../../src/omi_hil_rl/real/tag_follow_session.py)。

tag10边长51mm、tag12为64mm。X为base_link←camera，Z为TCP←tag10，平移以米保存。现场TCP、相机或标签安装改变后需重新标定；原ID0–7标记板结果不能直接替代。保存默认关系和跟随使用同一套变换约定。

原手柄LB+305保存、LB+304切换；SpacePilot配置ID2/8映射为对应事件，主配置关闭时不执行。训练内Actor仍唯一发布最终动作，跟随只用于复位；策略和回合计时暂停，control_epoch隔离旧候选，跟随动作不作为RL transition。独立脚本需独占输出，不能与训练同时抢占。

## 控制与边界

当前共用控制参数：平移/旋转增益0.08，每轴每周期上限0.5mm/0.2°；平移≤2.5mm、旋转≤0.8°独立归零，保持后分别超过3.5mm、1.2°才恢复。HOLDING仍监测目标，不等于退出跟随。

跟随用本地回调单调时间检查120ms新鲜度；header用于标定配对和诊断。接收新鲜不证明上游无滞后。失效归零，但现有训练内跟随状态不会自动切回策略；这是明确的控制状态，不能由故障恢复自动触发运动。

启用实现仍有Actor内图像转换/同步保存、退出等待检测线程的耦合。独立Marker节点、硬超时故障隔离和数字3总开关尚未实现。

## 证据与使用

10月17日20个样本X/Z平均平移残差3.03mm，通过当时3.5mm门槛；现场独立跟随试用后下调参数。内部残差及软件延迟模型不能代表独立闭环精度验收，训练内完整切换仍需现场验证。

操作见 [标定与跟随教程](../../tutorials/marker_detect.md)。当前主配置见 [在线基线](../../tutorials/spacepilot_bc6148_online_rl.md)，重新启用需要明确配置和现场验证。

开发历史（按需）：[Marker归档](../archive/marker/README.md)。
